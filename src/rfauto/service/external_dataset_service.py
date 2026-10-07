"""KD-8 外部数据集接入面+许可门（round16 KD-7 采纳口径，J 流）。

定位（任务书口径）：外部公开 RF 数据集的**接入器（schema 适配层）+
许可门**。铁律：**数据本体不入仓**——本模块零下载零网络，只产出
"接入计划"（下载到哪、怎么映射 schema、许可约束是什么），本体获取
由人/外部工具按计划执行。

许可门（NC 禁公开分发，round16 no-go 行）：
- 数据集许可注册表单源 ``LICENSE_REGISTRY``：permissive（CC-BY 等，
  可再分发）/ research_only（NC 类，如 RadioML 2016.10a——研究评测
  面可用，**公开分发/发布包/公开仓一律拒绝**）；
- 许可门是**硬门**：``use="publish"`` 对 research_only 数据集恒拒绝，
  无豁免开关（绕过=改代码=显式评审动作，不留运行时后门）；
- 未注册数据集如实 UNKNOWN 拒入（不猜许可）。

接入器（schema 适配层）：
- ``adapt_rows``：外部列名 → DATASET_SCHEMA 列白名单映射（列名映射
  显式声明；目标列不在 dataset_service.DATASET_SCHEMA =报错）；
- ``plan_ingestion``：接入计划=许可门裁定+目标路径守卫（**默认拒绝
  仓内路径**——数据本体不入仓；显式 allow_repo_gitinished_root 才放
  行 gitignored 根，且只认 runs）。

用法::

    from rfauto.service.external_dataset_service import (
        check_license_gate, plan_ingestion, adapt_rows)

    gate = check_license_gate("radioml2016.10a", use="research_eval")
    plan = plan_ingestion("ieee_dataport_microstrip_190k",
                          target_dir="E:/data/ext")   # 仓外路径
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.dataset_service import DATASET_SCHEMA
from rfauto.service.envelope import error_envelope, ok_envelope

#: 许可门契约版本。
EXTERNAL_DATASET_SCHEMA = "rfauto-external-dataset-v1"

#: 许可类别（受控词表）。
LICENSE_PERMISSIVE = "permissive"      # 可再分发（CC-BY/CC0/MIT 类）
LICENSE_RESEARCH_ONLY = "research_only"  # NC 类：研究评测面可用，禁公开分发

#: 用途受控词表。
USE_RESEARCH_EVAL = "research_eval"    # 研究评测（训练/评估/内部对照）
USE_PUBLISH = "publish"                # 公开分发（发布包/公开仓/外发附件）

#: 许可注册表单源（round16 KD-7 首批 + NC 铁律锚；新增数据集必须登记）。
LICENSE_REGISTRY: dict[str, dict[str, Any]] = {
    "ieee_dataport_microstrip_190k": {
        "license": LICENSE_PERMISSIVE, "license_name": "CC-BY 4.0",
        "source": "IEEE DataPort（190k 微带，round16 §三）",
        "notes": "再分发须附署名（CC-BY BY 义务）"},
    "zenodo_14533762": {
        "license": LICENSE_PERMISSIVE, "license_name": "CC-BY 4.0",
        "source": "Zenodo record 14533762（round16 §三）", "notes": ""},
    "mendeley_rf": {
        "license": LICENSE_PERMISSIVE, "license_name": "CC-BY 4.0",
        "source": "Mendeley Data（RF 族，round16 §三）", "notes": ""},
    "kaggle_rf": {
        "license": LICENSE_PERMISSIVE, "license_name": "见数据集页",
        "source": "Kaggle（RF 族，round16 §三）",
        "notes": "Kaggle 逐数据集条款——接入前人工复核该页"},
    # NC 铁律锚（round16 no-go：NC 数据集不入公开仓；RadioML 禁公开分发）
    "radioml2016.10a": {
        "license": LICENSE_RESEARCH_ONLY, "license_name": "CC-BY-NC 4.0",
        "source": "DeepSig RadioML 2016.10a（round16 §三）",
        "notes": "禁公开分发——只进研究评测面；数据本体不入仓不入发布包"},
    "radioml2016.10b": {
        "license": LICENSE_RESEARCH_ONLY, "license_name": "CC-BY-NC 4.0",
        "source": "DeepSig RadioML 2016.10b", "notes": "同 2016.10a NC 铁律"},
    "radioml2018.01a": {
        "license": LICENSE_RESEARCH_ONLY, "license_name": "CC-BY-NC 4.0",
        "source": "DeepSig RadioML 2018.01A", "notes": "同 2016.10a NC 铁律"},
}

#: 仓内唯一可放行的 gitignored 根（数据本体不入仓的窄豁免；runs/ 顶层
#: gitignored——放行目录须再经 plan 的 runs/external_datasets 约束）。
_REPO_GITIGNORED_ALLOWED_ROOTS = ("runs",)

#: 豁免根下唯一允许的子目录（外部数据集落地命名空间）。
_REPO_ALLOWED_SUBDIR = ("external_datasets",)


def _repo_root() -> Path:
    """仓根定位（本模块位于 <root>/src/rfauto/service/，parents[3]=仓根）。"""
    return Path(__file__).resolve().parents[3]


def check_license_gate(dataset_id: str, *, use: str = USE_RESEARCH_EVAL
                       ) -> dict[str, Any]:
    """许可门（硬门，确定性纯函数）。

    - 未注册数据集 → allowed=False, gate="UNKNOWN"（不猜许可，拒入）；
    - permissive 数据集 → research_eval/publish 均放行；
    - research_only 数据集 → research_eval 放行（须附 NC 注记），
      **publish 恒拒绝**（无豁免开关——NC 禁公开分发是铁律）；
    - use 词表外 → 拒绝（不猜用途）。
    """
    entry = LICENSE_REGISTRY.get(str(dataset_id))
    if entry is None:
        return {"ok": False, "schema": EXTERNAL_DATASET_SCHEMA,
                "dataset_id": str(dataset_id), "use": use,
                "allowed": False, "gate": "UNKNOWN",
                "reasons": ["数据集未注册许可（不猜许可，先登记 LICENSE_REGISTRY）"]}
    if use not in (USE_RESEARCH_EVAL, USE_PUBLISH):
        return {"ok": False, "schema": EXTERNAL_DATASET_SCHEMA,
                "dataset_id": str(dataset_id), "use": use,
                "allowed": False, "gate": entry["license"],
                "reasons": [f"use {use!r} 不在受控词表"
                            f"{{{USE_RESEARCH_EVAL},{USE_PUBLISH}}}"]}
    lic = entry["license"]
    if lic == LICENSE_PERMISSIVE:
        return ok_envelope(schema=EXTERNAL_DATASET_SCHEMA,
                           dataset_id=str(dataset_id), use=use,
                           allowed=True, gate=lic,
                           license_name=entry["license_name"],
                           reasons=([f"{entry['license_name']}：可再分发"]
                                    + ([f"注记：{entry['notes']}"] if entry["notes"] else [])))
    # research_only
    if use == USE_PUBLISH:
        return {"ok": False, "schema": EXTERNAL_DATASET_SCHEMA,
                "dataset_id": str(dataset_id), "use": use,
                "allowed": False, "gate": lic,
                "license_name": entry["license_name"],
                "reasons": [f"{entry['license_name']}（NC 类）禁公开分发"
                            "——publish 硬门无豁免；数据本体不入仓不入发布包"]}
    return ok_envelope(schema=EXTERNAL_DATASET_SCHEMA,
                       dataset_id=str(dataset_id), use=use,
                       allowed=True, gate=lic,
                       license_name=entry["license_name"],
                       reasons=[f"{entry['license_name']}：仅研究评测面可用"
                                f"（禁公开分发；{entry['notes']}）"])


def _target_guard(target_dir: str | Path, *,
                  allow_repo_gitignored: bool) -> tuple[bool, list[str]]:
    """目标路径守卫：默认拒绝仓内路径（数据本体不入仓）。

    显式 allow_repo_gitignored=True 才放行仓内 gitignored 根，且只认
    ``<root>/runs/external_datasets`` 命名空间（其余仓内路径照拒）。
    """
    p = Path(os.path.expanduser(str(target_dir)))
    reasons: list[str] = []
    try:
        p.relative_to(_repo_root())
        in_repo = True
    except ValueError:
        in_repo = False
    if not in_repo:
        return True, []
    if not allow_repo_gitignored:
        reasons.append(
            f"目标在仓内（{_repo_root()}）——数据本体不入仓；仓外路径或显式"
            " allow_repo_gitignored=True（只认 runs/external_datasets）")
        return False, reasons
    rel = p.relative_to(_repo_root())
    parts = rel.parts
    if (len(parts) < 1 or parts[0] not in _REPO_GITIGNORED_ALLOWED_ROOTS
            or len(parts) < 2 or parts[1] != _REPO_ALLOWED_SUBDIR[0]):
        reasons.append(
            "仓内豁免只认 runs/external_datasets 命名空间（gitignored）；"
            f"收到 {'/'.join(parts) or '.'}")
        return False, reasons
    return True, []


def plan_ingestion(dataset_id: str, target_dir: str | Path, *,
                   allow_repo_gitignored: bool = False,
                   source_uri: str | None = None) -> dict[str, Any]:
    """外部数据集接入计划（零下载零网络——计划面，本体由人按计划获取）。

    许可门（research_eval 口径）+ 目标路径守卫双双通过才 ok=True。
    返回计划含：许可约束（含禁分发注记）、目标目录、schema 映射模板
    （列名映射由接入方按数据集页显式补全后才能 adapt_rows）。
    """
    gate = check_license_gate(dataset_id, use=USE_RESEARCH_EVAL)
    target_ok, target_reasons = _target_guard(
        target_dir, allow_repo_gitignored=allow_repo_gitignored)
    ok = bool(gate.get("allowed")) and target_ok
    reasons = list(gate.get("reasons") or []) + target_reasons
    return {
        "ok": ok, "schema": EXTERNAL_DATASET_SCHEMA,
        "dataset_id": str(dataset_id),
        "source_uri": source_uri,
        "target_dir": os.path.abspath(os.path.expanduser(str(target_dir))),
        "license_gate": gate,
        "dataset_schema_columns": [c for c, _t in DATASET_SCHEMA],
        "schema_map": {},   # 接入方按数据集页显式补全（外部列→DATASET_SCHEMA 列）
        "steps": [
            "人工下载数据本体到 target_dir（本模块零下载零网络）",
            "补全 schema_map（外部列名→DATASET_SCHEMA 列白名单）",
            "adapt_rows 物化行 → dataset_service 收集面（visibility=private）",
        ],
        "reasons": reasons,
    }


#: 列名映射（dataset_id → {外部列: DATASET_SCHEMA 列}）；首批种子=空映射
#: 模板，逐数据集接入时显式登记（列名猜映射禁止）。
SCHEMA_MAP_SEEDS: dict[str, dict[str, str]] = {}


def adapt_rows(rows: Sequence[Mapping[str, Any]], schema_map: Mapping[str, str],
               *, dataset_id: str = "") -> dict[str, Any]:
    """外部行 → DATASET_SCHEMA 列白名单行（纯函数适配层）。

    - schema_map：{外部列: 目标列}；目标列不在 DATASET_SCHEMA =显式报错
      （白名单外列不静默丢弃也不静默透传）；
    - 必填目标列（run_id/model/adapter）映射缺失=报错（行级门会拦，
      接入面先拦）；
    - 未映射的外部列原样保留在 ``extra`` 键（数据零丢失，物化时可弃）。
    """
    target_cols = {c for c, _t in DATASET_SCHEMA}
    bad_targets = sorted({t for t in schema_map.values() if t not in target_cols})
    if bad_targets:
        return error_envelope(
            [f"schema_map 目标列不在 DATASET_SCHEMA: {bad_targets}"],
            schema=EXTERNAL_DATASET_SCHEMA, dataset_id=dataset_id)
    missing_required = [c for c in ("run_id", "model", "adapter")
                        if c not in schema_map.values()]
    if missing_required:
        return error_envelope(
            [f"schema_map 未覆盖必填目标列: {missing_required}"],
            schema=EXTERNAL_DATASET_SCHEMA, dataset_id=dataset_id)
    mapped_rows: list[dict[str, Any]] = []
    for row in rows:
        out: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for k, v in row.items():
            if k in schema_map:
                out[schema_map[k]] = v
            else:
                extra[k] = v
        out["extra"] = extra
        mapped_rows.append(out)
    return ok_envelope(schema=EXTERNAL_DATASET_SCHEMA,
                       dataset_id=dataset_id, n_rows=len(mapped_rows),
                       rows=mapped_rows,
                       errors=[])
