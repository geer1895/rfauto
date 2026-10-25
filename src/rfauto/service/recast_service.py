"""recast_service —— RECAST 判据重放服务面（core/recast 的 JSON 进出薄壳）。

教程 docs/tutorials/recast-walkthrough.md 的 CLI 出口（2026-10-11
aurora36 W2-D 清偿教程-代码断链：教程有 recast walkthrough 而 cli 零
recast 命令）。规则 4：本模块只做判据装载状态与重放报告的信封封装，
零重放逻辑；铁律 7：数值全部来自 core.recast 确定性重算（判据声明值
×产物证据字段），LLM/agent 永不经手物理数字。

两读表面（零写盘零归档改写——#325/#326 纪律在 core 侧已由只读输入
保证，本模块同样不落任何文件）：

- ``recast_status``：criteria/v2 注册面清单（含坏条目 error 如实登记）；
- ``recast_replay``：归档证据 JSON × 全部已注册判据批量重放（core
  replay_batch 单源），summary 三向计数 same/flip/not_judged——flip>0
  即人工仲裁信号，如实透传不吞。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.recast import load_criteria_dir, replay_batch
from rfauto.service.envelope import error_envelope, ok_envelope

#: 判据机器源缺省目录（仓根相对；教程与 criteria_index_build 同口径）
DEFAULT_CRITERIA_DIR = "knowledge/criteria/v2"
#: 单证据 JSON 读取上限（防误指巨型文件；判读档为 KB-MB 级）
_JSON_MAX_BYTES = 32 * 1024 * 1024


def recast_status(
    criteria_dir: str | Path = DEFAULT_CRITERIA_DIR,
) -> dict[str, Any]:
    """判据注册面状态（只读）：目录内 criteria/v2 YAML 装载清单。

    返回 ok/criteria_dir/n_criteria/n_criteria_ok/criteria（逐条 path/
    name/ok/criteria_id/decision_rule_form/errors）；目录不存在 →
    error 信封。
    """
    base = Path(criteria_dir)
    if not base.is_dir():
        return error_envelope([f"判据目录不存在: {base}"])
    entries = load_criteria_dir(base)
    listing = [{
        "path": e["path"],
        "name": e["name"],
        "ok": e["ok"],
        "criteria_id": e.get("criteria_id"),
        "decision_rule_form": e.get("decision_rule_form"),
        "errors": e.get("errors") or [],
    } for e in entries]
    return ok_envelope(
        criteria_dir=str(base),
        n_criteria=len(entries),
        n_criteria_ok=sum(1 for e in entries if e["ok"]),
        criteria=listing,
    )


def recast_replay(
    artifacts: dict[str, str | Path] | None = None,
    criteria_dir: str | Path = DEFAULT_CRITERIA_DIR,
    evidence_paths: dict[str, str] | None = None,
    archived_verdict_path: str | None = "verdict",
) -> dict[str, Any]:
    """归档证据 × 全部已注册判据批量重放（只读，零写盘）。

    artifacts = {重放名: 证据 JSON 文件路径}——路径只读装载，装载失败
    逐条登记进 artifact_errors 并继续（多故障叠加报告形态，与 core
    replay_batch 坏条目口径同向）；全部装载失败或未给 → error 信封。

    返回 ok/schema/criteria/pairs/summary/artifact_errors/replay_ok：
    replay_ok=core 报告自身判定（判据零错误且有重放对）；三向计数在
    summary（n_same/n_flip/n_not_judged），flip>0=人工仲裁信号如实透传。
    """
    base = Path(criteria_dir)
    if not base.is_dir():
        return error_envelope([f"判据目录不存在: {base}"])
    artifacts_map: dict[str, dict[str, Any]] = {}
    artifact_errors: list[str] = []
    for name, raw in (artifacts or {}).items():
        p = Path(raw)
        try:
            if p.stat().st_size > _JSON_MAX_BYTES:
                raise ValueError(f"证据文件超限（>{_JSON_MAX_BYTES} 字节）")
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            artifact_errors.append(f"{name} <- {p}: 证据装载失败（{exc}）")
            continue
        if not isinstance(data, dict):
            artifact_errors.append(f"{name} <- {p}: 证据根必须是 JSON 对象")
            continue
        artifacts_map[str(name)] = data
    if not artifacts_map:
        return error_envelope(
            ["没有可重放证据（未给 --artifact 或全部装载失败）",
             *artifact_errors])
    report = replay_batch(
        artifacts_map, base,
        evidence_paths=evidence_paths,
        archived_verdict_path=archived_verdict_path)
    result = ok_envelope(
        schema=report.get("schema"),
        criteria=report.get("criteria") or [],
        pairs=report.get("pairs") or [],
        summary=report.get("summary") or {},
        artifact_errors=artifact_errors,
        replay_ok=bool(report.get("ok")),
    )
    if artifact_errors:
        result["warnings"] = [*result.get("warnings", []), *artifact_errors]
    return result
