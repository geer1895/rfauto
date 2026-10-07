"""R2 模型档案（收窄版）：代理/闭式模型卡 + 运行史卡（只读）。

规格口径（monthly_enhancement_plan F 流 R2 收窄 + QW-16 联动）：
- 收窄 = 不做全档案治理面，只落 {model_id, kind, created, params_schema,
  criteria_refs, last_runs, drift_status} 结构化卡 + 漂移监控接线；
- 数据源只读（surrogate 注册表 / 计算器注册表 / runs 湖 / 锚注册表），
  本模块零写路径；
- drift_status 消费 QW-16（service/anchors_service.anchor_drift_status）：
  lake 卡经锚 template_family（含通配 ``*``）联动锚面，出各锚漂移 verdict；
  registry 卡无残差序列，如实 no_data（数据积累期语义见
  core/anchor_drift 模块 docstring）。

两种卡：
- ``source="registry"``：model_id ∈ 代理注册表键（kind="surrogate"）或
  计算器注册表键（kind="closed_form"）——代码工件卡；
- ``source="lake"``：model_id = runs 湖里的模型族（meta.json 的 ``model``
  字段，其次战役目录名）——运行史卡（kind="run_history"）。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.optimization.surrogate.base import surrogate_registry
from rfauto.service.anchors_service import anchor_drift_status
from rfauto.service.envelope import ok_envelope

#: 锚 template_family 通配键（anchors.yaml cps.gamma_er 口径）
_ANCHOR_FAMILY_WILDCARD = "*"

_VERDICT_NAME = "verdict.json"
_CRITERIA_NAMES = ("criteria.md", "criteria.yaml")

#: drift verdict 劣化序（越大越劣；lake 卡聚合取最劣）
_VERDICT_RANK = {"drifted": 4, "warning": 3, "insufficient": 2,
                 "no_data": 1, "stable": 0}


def _registry_surrogate_param_schema(kind: str) -> list[dict[str, Any]] | None:
    """代理工厂签名 → params_schema（拿不到如实 None，不臆造）。"""
    factories = getattr(surrogate_registry, "_factories", {})
    factory = factories.get(kind)
    if factory is None:
        return None
    try:
        sig = inspect.signature(factory.__init__)
    except (TypeError, ValueError):
        return None
    rows = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        default: Any = "<required>" if param.default is inspect.Parameter.empty \
            else repr(param.default)
        rows.append({"name": name, "default": default,
                     "annotation": (str(param.annotation)
                                    if param.annotation
                                    is not inspect.Parameter.empty
                                    else None)})
    return rows


def _closed_form_param_schema(name: str) -> list[dict[str, Any]] | None:
    """计算器注册表 describe() → params_schema。"""
    for spec in CALCULATOR_REGISTRY.describe(include_experimental=True):
        if spec["name"] == name:
            return spec["params"]
    return None


def registry_model_ids() -> dict[str, list[str]]:
    """registry 卡全集（{surrogate: [...], closed_form: [...]}，字典序）。"""
    return {
        "surrogate": sorted(surrogate_registry.available()),
        "closed_form": CALCULATOR_REGISTRY.names(include_experimental=True),
    }


def _scan_runs_meta(runs_dir: str | Path) -> list[dict[str, Any]]:
    """只读扫 runs/（一级+二级目录）meta.json，行=湖索引同构最小集。

    与 lake_service.build_runs_index 同口径（存在才读、缺失跳过、单目录
    失败不阻塞），但不建库——模型卡枚举是轻量只读面。
    """
    root = Path(runs_dir)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for depth1 in sorted(root.iterdir()):
        if not depth1.is_dir():
            continue
        candidates = [(depth1, depth1.name)]
        for depth2 in sorted(depth1.iterdir()):
            if depth2.is_dir():
                candidates.append((depth2, depth1.name))
        for run_dir, campaign in candidates:
            meta_path = run_dir / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            verdict = None
            verdict_path = run_dir / _VERDICT_NAME
            if verdict_path.is_file():
                try:
                    verdict = (json.loads(
                        verdict_path.read_text(encoding="utf-8"))
                        or {}).get("verdict")
                except (OSError, ValueError):
                    verdict = None
            rows.append({
                "path": run_dir.relative_to(root).as_posix(),
                "run_id": run_dir.name,
                "campaign": campaign,
                "model": (str(meta["model"])
                          if meta.get("model") is not None else None),
                "adapter": (str(meta["adapter"])
                            if meta.get("adapter") is not None else None),
                "study": (str(meta["study_name"])
                          if meta.get("study_name") is not None else None),
                "status": (str(meta["status"])
                           if meta.get("status") is not None else None),
                "created_ts": (str(meta["timestamp"])
                               if meta.get("timestamp") is not None
                               else None),
                "verdict": (str(verdict) if verdict is not None else None),
            })
    return rows


def _lake_model_families(runs_dir: str | Path) -> dict[str, int]:
    """runs 湖里的模型族 → 出现次数（meta.model 非空值计数）。"""
    counts: dict[str, int] = {}
    for row in _scan_runs_meta(runs_dir):
        family = row["model"]
        if family:
            counts[family] = counts.get(family, 0) + 1
    return counts


def _linked_anchor_drift(model_id: str, *, anchors_path: str | None,
                         store_path: str | Path | None) -> dict[str, Any]:
    """QW-16 接线：template_family（含 * 通配）覆盖该模型族的锚漂移聚合。"""
    from rfauto.infra.anchors_store import load_anchors

    anchor_set = load_anchors(anchors_path)
    linked = [rec for rec in anchor_set.records
              if model_id in rec.template_family
              or _ANCHOR_FAMILY_WILDCARD in rec.template_family]
    if not linked:
        return {"available": False, "verdict": "no_data",
                "reason": f"无 template_family 覆盖 {model_id} 的锚"
                          "（含 * 通配）", "anchors": []}
    rows = []
    for rec in linked:
        status = anchor_drift_status(rec.anchor_id, None, path=anchors_path,
                                     store_path=store_path)
        rows.append({"anchor_id": rec.anchor_id,
                     "status": rec.status,
                     "verdict": (status["report"]["verdict"]
                                 if status.get("ok") else "no_data"),
                     "last_verified_residual":
                         status.get("last_verified_residual")})
    worst = max((_VERDICT_RANK.get(r["verdict"], 1) for r in rows),
                default=1)
    worst_verdict = next(v for v, rank in _VERDICT_RANK.items()
                         if rank == worst)
    return {"available": True, "verdict": worst_verdict,
            "reason": f"{len(rows)} 个联动锚（按最劣聚合）", "anchors": rows}


def build_model_card(
    model_id: str,
    source: str = "registry",
    *,
    runs_dir: str | Path = "runs",
    anchors_path: str | None = None,
    store_path: str | Path | None = None,
    last_runs_limit: int = 5,
) -> dict[str, Any]:
    """构建单张模型卡（只读；{model_id, kind, created, params_schema,
    criteria_refs, last_runs, drift_status}）。

    Args:
        model_id: 模型标识（registry=代理键/计算器键；lake=模型族或战役名）。
        source: ``"registry"``（代码工件卡）或 ``"lake"``（运行史卡）。
        runs_dir: lake 卡的 runs 根（只读扫）。
        anchors_path: 锚注册表路径覆盖（QW-16 联动用）。
        store_path: 指纹快照库路径覆盖（QW-16 联动用）。
        last_runs_limit: lake 卡 last_runs 摘要条数（按 created_ts 降序）。

    Returns:
        卡 dict（ok=True）或 {ok: False, error, available: ...}。
    """
    model_id = str(model_id)
    if source == "registry":
        ids = registry_model_ids()
        if model_id in ids["surrogate"]:
            return ok_envelope(
                model_id=model_id,
                kind="surrogate",
                source="registry",
                created=None,
                created_note="代码工件（注册表面无创建时刻语义）",
                params_schema=_registry_surrogate_param_schema(model_id),
                criteria_refs=[],
                criteria_note="registry 卡暂无按模型键的判据资产"
                                 "（criteria 资产按 run 归档）",
                last_runs=[],
                drift_status={
                    "available": False, "verdict": "no_data",
                    "reason": "registry 卡无残差序列；漂移监控经 lake 卡"
                              "联动锚面（QW-16 快照机制数据积累期）",
                    "anchors": []},
            )
        if model_id in ids["closed_form"]:
            return ok_envelope(
                model_id=model_id,
                kind="closed_form",
                source="registry",
                created=None,
                created_note="代码工件（注册表面无创建时刻语义）",
                params_schema=_closed_form_param_schema(model_id),
                criteria_refs=[],
                criteria_note="registry 卡暂无按模型键的判据资产"
                                 "（criteria 资产按 run 归档）",
                last_runs=[],
                drift_status={
                    "available": False, "verdict": "no_data",
                    "reason": "registry 卡无残差序列；漂移监控经 lake 卡"
                              "联动锚面（QW-16 快照机制数据积累期）",
                    "anchors": []},
            )
        return {"ok": False,
                "error": f"registry 无模型 {model_id!r}（代理: "
                         f"{ids['surrogate']}；闭式: {ids['closed_form']}）",
                "available": ids}
    if source == "lake":
        rows = _scan_runs_meta(runs_dir)
        matched = [r for r in rows if r["model"] == model_id]
        if not matched:  # 回退：按战役目录名匹配（模型族缺 meta.model 时）
            matched = [r for r in rows if r["campaign"] == model_id]
        if not matched:
            return {"ok": False,
                    "error": f"lake 无模型族 {model_id!r}",
                    "available": sorted(_lake_model_families(runs_dir))}
        matched.sort(key=lambda r: (r["created_ts"] or "", r["path"]))
        created = next((r["created_ts"] for r in matched
                        if r["created_ts"]), None)
        criteria_refs: list[str] = []
        seen_dirs: set[str] = set()
        for r in matched:
            run_dir = Path(runs_dir) / r["path"]
            if r["path"] in seen_dirs:
                continue
            seen_dirs.add(r["path"])
            for name in _CRITERIA_NAMES:
                if (run_dir / name).is_file():
                    criteria_refs.append(f"{r['path']}/{name}")
        ranked = sorted(matched, key=lambda r: r["created_ts"] or "",
                        reverse=True)[:max(0, int(last_runs_limit))]
        return ok_envelope(
            model_id=model_id,
            kind="run_history",
            source="lake",
            created=created,
            created_note="匹配 run 的最早 timestamp",
            params_schema=None,
            params_note="run 史不承载参数 schema（见 registry 卡）",
            criteria_refs=sorted(criteria_refs),
            criteria_note="匹配 run 目录内预声明判据资产",
            last_runs=[{"path": r["path"], "run_id": r["run_id"],
                           "created_ts": r["created_ts"],
                           "status": r["status"], "adapter": r["adapter"],
                           "verdict": r["verdict"]} for r in ranked],
            n_matched_runs=len(matched),
            drift_status=_linked_anchor_drift(
                model_id, anchors_path=anchors_path, store_path=store_path),
        )
    return {"ok": False, "error": f"未知 source: {source!r}"
                                  "（registry|lake）", "available": {}}


def list_model_cards(
    *, runs_dir: str | Path = "runs", anchors_path: str | None = None,
    store_path: str | Path | None = None,
) -> dict[str, Any]:
    """模型卡清单（registry 全集 + lake 模型族，slim 行）。

    Returns:
        {ok, counts: {surrogate, closed_form, run_history}, cards:
        [{model_id, kind, source, ...slim}]}；lake 面按 runs/ 实扫。
    """
    ids = registry_model_ids()
    cards: list[dict[str, Any]] = []
    for kind in ("surrogate", "closed_form"):
        for model_id in ids[kind]:
            cards.append({"model_id": model_id, "kind": kind,
                          "source": "registry"})
    families = _lake_model_families(runs_dir)
    for family in sorted(families):
        cards.append({"model_id": family, "kind": "run_history",
                      "source": "lake", "n_runs": families[family]})
    return ok_envelope(
        counts={"surrogate": len(ids["surrogate"]),
                       "closed_form": len(ids["closed_form"]),
                       "run_history": len(families)},
        cards=cards,
        note="完整卡经 build_model_card(model_id, source) 取",
    )
