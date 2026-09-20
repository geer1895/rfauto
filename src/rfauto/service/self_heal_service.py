"""自愈环 / LogDistiller 生产接线信封（WP3.5 F5 + WP3.6 消费端装车）。

早期审查修复（"接线层"类缺口）：
pipeline/self_heal.self_heal_loop 与 pipeline/log_distiller 此前生产零调用
（仅测试引用）。本模块把它们装进三条只读生产路径：

- write_log_digest_for_run：run 收尾落盘后的 best-effort 钩子——把 run 目录
  日志面蒸馏成 runs/<id>/log_digest.json（service/api.run_once 收尾消费；
  任何异常吞掉只记 warning，#105：观测性代码不得成为主路径故障点）
- self_heal_run_for_run：对既有 run 跑一次只读自愈环（attempt=重读日志面，
  零真机、零网络），返回确定性 critique 审计 JSON；**只诊断+建议，不自动改
  配方**——落地动作仍走既有三层 Gate/沙箱（agent propose/apply）
- log_digest_for_path：任意日志文件/审计 JSON/run 目录 → 结构化 digest
  （CLI rfauto logs digest / MCP log_digest 的同源信封）

纪律：数值与判定只出自确定性内核（log_distiller.distill_log /
self_heal.critique_failure，铁律 7）；本模块不做任何物理推断，不打印
stdout（MCP 协议通道保护，#242）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 纳入日志面的产物后缀（其余 = 二进制/图件/S 参数，不进蒸馏）
_LOG_SURFACE_SUFFIXES = (".log", ".txt", ".json", ".md", ".yaml")
#: 本模块自己的产物——排除，防止上次 digest 回灌本次蒸馏
_DIGEST_NAME = "log_digest.json"
#: 单 run 日志面拼接上限（字符；保留尾部=最近输出，与 distill 的尾部口径一致）
_MAX_SURFACE_CHARS = 400_000
#: 单 run 最多纳入的产物文件数（防异常大目录）
_MAX_SURFACE_FILES = 50


def collect_run_log_surface(
    run_dir: str | Path,
    *,
    max_chars: int = _MAX_SURFACE_CHARS,
    max_files: int = _MAX_SURFACE_FILES,
) -> str:
    """收集 run 目录的日志面（确定性：按相对路径排序、限量截尾）。

    只读；目录不存在返回空串。#140：注解写 Path 不代表调用方传 Path。
    """
    root = Path(run_dir)
    if not root.is_dir():
        return ""
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == _DIGEST_NAME:
            continue
        if path.suffix.lower() not in _LOG_SURFACE_SUFFIXES:
            continue
        candidates.append(path)
        if len(candidates) >= max_files:
            break
    candidates.sort(key=lambda p: str(p.relative_to(root)))
    parts: list[str] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # best-effort：单个产物读失败不影响整体
        rel = path.relative_to(root).as_posix()
        parts.append(f"=== {rel} ===\n{text}")
    combined = "\n".join(parts)
    if len(combined) > max_chars:
        combined = combined[-max_chars:]
    return combined


def write_log_digest_for_run(run_dir: str | Path) -> dict[str, Any]:
    """run 收尾钩子：日志面 → log_distiller 蒸馏 → <run_dir>/log_digest.json。

    best-effort（#105）：任何异常吞掉只记 warning，绝不向调用方抛；
    无可蒸馏内容（空 run/目录缺失）则跳过不写文件。返回信封供审计：
    {ok, skipped?, path?, digest?, reason?}。
    """
    try:
        root = Path(run_dir)
        surface = collect_run_log_surface(root)
        if not surface.strip():
            return {"ok": True, "skipped": True, "reason": "无可蒸馏日志面（空 run/目录缺失）"}
        from rfauto.pipeline.log_distiller import distill_log

        digest = distill_log(surface, source="auto")
        out_path = root / _DIGEST_NAME
        out_path.write_text(
            json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        return {"ok": True, "path": str(out_path), "digest": digest}
    except Exception as exc:  # 观测性兜底：宁可 unknown 也不阻塞收尾（#105）
        logger.warning("log_digest 落盘失败（非阻断）: %s", exc)
        return {"ok": False, "skipped": True, "reason": f"蒸馏/落盘异常（已降级）: {exc!r}"}


def self_heal_run_for_run(
    run_id: str,
    *,
    retries: int = 0,
    runs_root: str | Path = "runs",
) -> dict[str, Any]:
    """对既有 run 跑一次只读自愈环（F5 装车：MCP self_heal_run / CLI 同源）。

    attempt = 重读该 run 的日志面（零真机、零网络、零副作用）；
    critique 由 pipeline/self_heal.critique_failure 确定性产出（11 失败签名
    根因目录），llm_explainer 恒不注入（铁律 7：llm_used 如实为 False）。

    **只诊断+建议**：返回 actions 供人工/编排参考，本函数不改任何配方——
    落地动作走既有三层 Gate/沙箱（rfauto agent-propose/apply）。
    """
    root = Path(runs_root) / run_id
    if not (root / "meta.json").is_file():
        return {
            "ok": False,
            "errors": [f"run 不存在或缺少 meta.json: runs/{run_id}"],
        }
    surface = collect_run_log_surface(root)
    from rfauto.pipeline.self_heal import self_heal_loop

    loop_result = self_heal_loop(lambda: surface, retries=max(0, int(retries)))
    critique = loop_result.get("critique")
    return {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(root),
        "attempts": loop_result.get("attempts"),
        "verdict": critique["verdict"] if critique else "clean",
        "root_cause_id": critique.get("root_cause_id") if critique else None,
        "root_cause": critique.get("root_cause") if critique else None,
        "lesson_ref": critique.get("lesson_ref") if critique else None,
        "severity": critique.get("severity") if critique else None,
        "causes": critique.get("causes", []) if critique else [],
        "actions": critique.get("actions", []) if critique else [],
        "signatures": critique.get("signatures", []) if critique else [],
        "digest": critique.get("digest") if critique else None,
        "history": loop_result.get("history", []),
        "log_surface_chars": len(surface),
        "llm_used": loop_result.get("llm_used", False),
        "llm_explainer_available": loop_result.get("llm_explainer_available", False),
        "advisory_only": True,
        "note": "只读诊断+建议：不自动修改配方；落地动作走三层 Gate/沙箱（agent propose/apply）",
    }


def log_digest_for_path(
    path: str | Path,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    """日志文件/审计 JSON/run 目录 → 结构化 digest（WP3.6 装车薄壳信封）。

    目录输入按 run 日志面口径蒸馏（collect_run_log_surface）；文件输入直接
    distill_file。只读，不落任何文件；解析失败由内核降级为 ok=False digest
    （#105），路径不存在才返回信封级错误。
    """
    target = Path(path)
    if not target.exists():
        return {"ok": False, "errors": [f"路径不存在: {target}"]}
    from rfauto.pipeline.log_distiller import distill_file, distill_log

    if target.is_dir():
        digest = distill_log(collect_run_log_surface(target), source=source)
    else:
        digest = distill_file(target, source=source)
    return {"ok": True, "path": str(target), "digest": digest}
