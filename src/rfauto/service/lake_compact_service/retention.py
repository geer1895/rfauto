"""lake_compact_service.retention —— ① h5 白名单保留策略（纯读规划+直删执行）。

自 service/lake_compact_service.py 单文件巨石按职责域拆分（架构批 W3-S1，
T2 范式/AU-1 工艺）：代码体自原节「① h5 白名单保留策略（纯读规划器）」
逐字节搬迁（指针源扫描/保护链判定/plan 三档规划/apply 白名单点名删除），
零逻辑改动；reversible/et_ht_dedup 域的保护面扫描从这里单向导入。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import (
    _git_head_short,
    _meta_file,
    _norm,
    _norm_under,
    _read_json_object,
    _repo_root_guess,
)

#: 目录名启发 token（§5.1 实测在：cps_hfss_arbitration、ge6_hfsswin 等）。
#: 宁保守（多保 = 少删）；命中即 name_heuristic 整目录保留。
HEURISTIC_TOKENS: tuple[str, ...] = (
    "anchor", "arbitration", "arb", "hfsswin", "golden", "review", "gate",
)

#: 判读产物在档标记（§5.2① 判读完成判据的"判读产物在档"分支；meta.status
#: ∈ judged/analyzed 为另一分支）
JUDGED_STATUSES: frozenset[str] = frozenset({"judged", "analyzed"})
JUDGED_ARTIFACTS: tuple[str, ...] = (
    "verdict.json", "arbverdict.json", "metrics.json", "sim_ci_report.json",
    "curve_verdict.json",
)


_H5_SUFFIX = ".h5"

_RUNS_POINTER_RE = re.compile(r"runs/[A-Za-z0-9_\-./]+")


#: 指针源缺省清单：(相对仓根路径, 理由分类)。simci_baseline.yaml 是 XD-5
#: pin 落点（XD-5 未执行时文件不存在→该源零指针，如实）。
DEFAULT_POINTER_SOURCES: tuple[tuple[str, str], ...] = (
    ("knowledge/anchors.yaml", "anchor_evidence"),
    ("knowledge/simci_baseline.yaml", "baseline_ref"),
    ("knowledge/formula_provenance.yaml", "golden_judged"),
    ("knowledge/trace_matrix.yaml", "golden_judged"),
)


# ---------------------------------------------------------------------------
# ① h5 白名单保留策略（纯读规划器）
# ---------------------------------------------------------------------------

def extract_pointer_dirs(
    runs_root: str | Path,
    pointer_sources: list[tuple[str | Path, str]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """扫指针源（宁保守全文 regex，不挑字段——devlog/provenance 提及也算）
    → 归一 run 目录 → [{category, source, pointer}]。

    指针三类解析：runs/ 路径指针（解析到 runs 根下存在的最深祖先目录）；
    simci 基线 run_id（pinned_run_id/model_run_ids 值，按目录名末段匹配）；
    其余忽略。pointer_sources 缺省 DEFAULT_POINTER_SOURCES（相对仓根），
    文件不存在如实跳过（XD-5 未 pin=该源零指针）。
    """
    root = Path(runs_root).resolve()
    root_norm = _norm(root)
    sources = pointer_sources if pointer_sources is not None \
        else [(Path(_repo_root_guess()) / rel, cat)
              for rel, cat in DEFAULT_POINTER_SOURCES]
    hit: dict[str, list[dict[str, str]]] = {}
    run_dirs: list[Path] | None = None

    def _protect_dir(directory: Path, category: str, source: str,
                     pointer: str) -> None:
        norm = _norm(directory)
        if not norm.startswith(root_norm + os.sep) and norm != root_norm:
            return
        hit.setdefault(norm, []).append(
            {"category": category, "source": source, "pointer": pointer})

    for source_path, category in sources:
        src = Path(source_path)
        if not src.is_file():
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _RUNS_POINTER_RE.findall(text):
            pointer = match.rstrip("./").rstrip("/")
            target = root / Path(pointer).relative_to("runs")
            # 解析到存在的最深祖先（指针可指向 run 目录内文件）
            probe = target
            while probe.exists() and not probe.is_dir():
                probe = probe.parent
            resolved = probe if probe.is_dir() else target
            # 锚证据整目录保留语义：指针落点向上归到最近 meta run 目录
            # （指针常指向 run 内产物文件；只护子目录会漏同 run 其他产物）
            if resolved.is_dir():
                meta_dir = _nearest_meta_dir(resolved, root)
                if meta_dir is not None:
                    resolved = meta_dir
            _protect_dir(resolved, category, src.name, pointer)
        # simci 基线 run_id 面（非 runs/ 路径形态；XD-5 pin 落点字段）
        if category == "baseline_ref":
            ids: list[str] = []
            try:
                import yaml

                data = yaml.safe_load(text)
            except Exception:
                data = None
            if isinstance(data, dict):
                if data.get("pinned_run_id"):
                    ids.append(str(data["pinned_run_id"]))
                mr = data.get("model_run_ids")
                if isinstance(mr, dict):
                    ids.extend(str(v) for v in mr.values())
            if not ids:
                ids = re.findall(r"pinned_run_id:\s*['\"]?([\w.\-]+)", text)
            if ids:
                if run_dirs is None:
                    run_dirs = _all_run_dirs(root)
                for run_id in {i.strip("'\"") for i in ids if i}:
                    for d in run_dirs:
                        if d.name == run_id:
                            _protect_dir(d, category, src.name, run_id)
    return hit


def _all_run_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__pycache__"]
        out.append(Path(dirpath))
    return out


def _nearest_meta_dir(path: Path, root: Path) -> Path | None:
    """自 path 向上找最近含 meta 的祖先（含自身）；越过 runs 根止。"""
    probe = path if path.is_dir() else path.parent
    while True:
        if _meta_file(probe) is not None:
            return probe
        if _norm(probe) == _norm(root):
            return None
        parent = probe.parent
        if parent == probe:
            return None
        probe = parent


def _dir_is_name_protected(directory: Path) -> bool:
    name = directory.name.lower()
    return any(tok in name for tok in HEURISTIC_TOKENS)


def _chain_protected(run_dir: Path, root: Path,
                     pointer_hits: dict[str, list[dict[str, str]]],
                     ) -> str | None:
    """run 目录→root 的祖先链上，指针命中优先、目录名启发次之；命中返回
    保留理由类（指针目录整目录保留——含其下全部子目录的 h5）。"""
    probe: Path | None = run_dir
    while probe is not None and _norm(probe) != _norm(root.parent):
        norm = _norm(probe)
        if norm in pointer_hits:
            return pointer_hits[norm][0]["category"]
        if probe != root and _dir_is_name_protected(probe):
            return "name_heuristic"
        if norm == _norm(root):
            break
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    return None


def _dir_judged(run_dir: Path, meta: dict[str, Any], *,
                require_status: bool) -> bool:
    status = str(meta.get("status") or "").lower()
    if status in JUDGED_STATUSES:
        return True
    if require_status:
        return False
    return any((run_dir / a).is_file() for a in JUDGED_ARTIFACTS)


def _dir_recent(directory: Path, meta_path: Path | None,
                min_age_h: float, now: float) -> bool:
    src = meta_path if meta_path is not None else directory
    try:
        mtime = src.stat().st_mtime
    except OSError:
        return True  # 判不了 = 当新近处理（宁保守）
    return (now - mtime) < max(0.0, min_age_h) * 3600.0


def _run_sort_key(run_dir: Path, meta_path: Path | None) -> str:
    """recent-n 排序键：meta.timestamp 字典序（ISO 等价时间序）→ mtime。"""
    meta = _read_json_object(meta_path) if meta_path is not None else None
    ts = str((meta or {}).get("timestamp") or "")
    if ts:
        return f"ts:{ts}"
    try:
        return f"mt:{run_dir.stat().st_mtime:.6f}"
    except OSError:
        return "mt:0"


def _meta_mtime(meta_path: Path | None) -> float | None:
    if meta_path is None:
        return None
    try:
        return meta_path.stat().st_mtime
    except OSError:
        return None


def _validate_exempt_subtrees(
    runs_root: Path,
    exempt_subtrees: list[str] | tuple[str, ...] | None,
) -> tuple[dict[str, str], list[str]]:
    """豁免子树清单校验 → (归一子树根 → 相对 posix 名) 映射 + 回显清单。

    白名单口径（W6-G 用户裁决）：仅显式点名的子树解除 no_meta_inflight
    保护；路径必须为 runs_root 下的相对 posix 目录（拒绝绝对/穿越/盘符/
    反斜杠——写面前守卫同族），且目录必须存在。
    """
    if not exempt_subtrees:
        return {}, []
    out: dict[str, str] = {}
    seen: list[str] = []
    for raw in exempt_subtrees:
        rel = str(raw).strip().replace("\\", "/").rstrip("/")
        if not rel or rel.startswith("/") or ":" in rel:
            raise ValueError(f"豁免子树非法（须为相对 posix 路径）: {raw!r}")
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError(f"豁免子树非法（穿越/绝对路径）: {raw!r}")
        if re.search(r"[^A-Za-z0-9_\-./]", rel):
            raise ValueError(f"豁免子树含非法字符: {raw!r}")
        target = runs_root / pure
        if not target.is_dir():
            raise ValueError(f"豁免子树不存在: {runs_root / pure}")
        norm = _norm(target)
        if norm not in out:
            out[norm] = pure.as_posix()
            seen.append(pure.as_posix())
    return out, seen


def plan_h5_retention(
    runs_root: str | Path = "runs",
    *,
    tier: str = "medium",
    keep_recent_n: int = 0,
    min_age_h: float = 24.0,
    pointer_sources: list[tuple[str | Path, str]] | None = None,
    max_rows: int = 500,
    exempt_subtrees: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """h5 白名单保留策略规划（**纯读**，零写零删——dry-run 判据本体）。

    分类单元 = run 目录（含 h5 文件的最近 meta 祖先目录；无 meta 祖先=
    在跑/半途 #144 形态）。保留理由优先级：anchor_evidence / baseline_ref /
    golden_judged（指针源命中，祖先链上任一目录命中即整目录保留）>
    name_heuristic（祖先链目录名启发）> no_meta_inflight >
    recent_activity（min_age_h 内有 meta 落盘动作）> recent_n_kept（同战役
    最新 N 个候选 run 豁免，"普通 trial h5 留 N 份最新"用户裁材料）>
    none（可删候选）。

    ``exempt_subtrees``（W6-G 用户豁免口径，缺省 None=行为逐字节不变）：
    显式点名子树解除 no_meta_inflight 保护——仅当 h5 无 meta 祖先 **且**
    相对路径落在点名子树内才成为可删候选（reason=user_exempt_subtree，
    行带 exempt_subtree 字段）；指针源/目录名启发保护**优先于豁免**
    （golden 零改写红线不因豁免松动）；豁免行仍受 min_age_h 新近检查
    （h5 文件自身 mtime）。未点名子树（含其余全部无 meta 子树）维持保护
    不进删除清单。

    三档口径（§5.4 材料不替裁）：
    - conservative：仅 meta.status ∈ judged/analyzed 的 run 可删；
    - medium：判读完成判据全条（status 或判读产物在档）；
    - aggressive：有 meta 即可删（状态不挑）。
    豁免行=用户已裁，三档均计入。三档 n_delete/bytes_delete **全部**
    给出（tiers 节），主清单按 tier 参数。

    Returns:
        dict: {"ok", "runs_root", "tier", "n_h5", "total_bytes",
        "delete": [{path, run_dir, size, reason, exempt_subtree?}], "n_delete",
        "bytes_delete", "keep_reasons", "tiers", "n_protected_dirs",
        "exempt_subtrees", "golden_rewrite_audit"}——audit.violations 恒空即
        golden 零改写断言通过（脚本断言，非人工抽查，spec §5.3 判据 1）。
    """
    root = Path(runs_root).resolve()
    base: dict[str, Any] = {"runs_root": str(root), "tier": tier}
    if tier not in ("conservative", "medium", "aggressive"):
        return error_envelope([f"tier 非法: {tier!r}（conservative/medium/"
                               "aggressive）"], **base)
    if not root.is_dir():
        return error_envelope([f"runs 根不存在: {root}"], **base)
    try:
        exempt_map, exempt_echo = _validate_exempt_subtrees(
            root, exempt_subtrees)
    except ValueError as exc:
        return error_envelope([str(exc)], **base)

    pointer_hits = extract_pointer_dirs(root, pointer_sources)
    now = time.time()
    h5_files = [p for p in root.rglob("*")
                if p.suffix.lower() == _H5_SUFFIX and p.is_file()]
    h5_files.sort()
    store_norm = _norm(root / ".blob_store")

    keep_reasons: dict[str, int] = {}
    delete_rows: list[dict[str, Any]] = []
    # 目录级判定缓存（同目录多 h5 只判一次）：norm → 目录信息
    dir_cache: dict[str, dict[str, Any]] = {}
    campaign_runs: dict[str, list[tuple[str, str]]] = {}
    tiers: dict[str, dict[str, Any]] = {}

    total_bytes = 0
    n_h5 = 0

    def _dir_info(norm: str, run_dir: Path) -> dict[str, Any]:
        cached = dir_cache.get(norm)
        if cached is not None:
            return cached
        meta_path = _meta_file(run_dir)
        meta = _read_json_object(meta_path) if meta_path is not None else {}
        status = str((meta or {}).get("status") or "").lower()
        has_artifact = any((run_dir / a).is_file()
                           for a in JUDGED_ARTIFACTS)
        info = {
            "tier_ok": {
                "conservative": status in JUDGED_STATUSES,
                "medium": status in JUDGED_STATUSES or has_artifact,
                "aggressive": True,
            },
            "meta_mtime": _meta_mtime(meta_path),
        }
        dir_cache[norm] = info
        return info

    for h5 in h5_files:
        try:
            size = h5.stat().st_size
        except OSError:
            continue
        n_h5 += 1
        total_bytes += size
        if _norm(h5).startswith(store_norm + os.sep):
            keep_reasons["blob_store"] = keep_reasons.get("blob_store", 0) + 1
            continue
        run_dir = _nearest_meta_dir(h5, root)
        if run_dir is None:
            # 无 meta 祖先 = 在跑/半途（#144）——任何档都不可删；
            # 例外：用户显式豁免子树（W6-G 白名单口径）解除本保护，
            # 指针/名字启发保护已在祖先链判定之外另行兜底（豁免不松动）。
            try:
                rel_h5 = h5.relative_to(root).as_posix()
            except ValueError:
                rel_h5 = h5.as_posix()
            exempt_hit = _exempt_hit(rel_h5, exempt_map)
            if exempt_hit is None:
                keep_reasons["no_meta_inflight"] = \
                    keep_reasons.get("no_meta_inflight", 0) + 1
                continue
            subtree_root = root / exempt_hit
            norm = _norm(subtree_root)
            # 豁免只解除 no_meta 保护；指针/名字启发保护按文件自身祖先链
            # 原粒度生效（子树内受保护深目录的 h5 仍保留）。
            if _chain_protected(h5.parent, root, pointer_hits) is not None:
                keep_reasons["no_meta_inflight"] = \
                    keep_reasons.get("no_meta_inflight", 0) + 1
                continue
            if _dir_recent(h5, None, min_age_h, now):
                keep_reasons["recent_activity"] = \
                    keep_reasons.get("recent_activity", 0) + 1
                continue
            delete_rows.append({
                "path": rel_h5,
                "run_dir": exempt_hit,
                "size": size,
                "reason": "user_exempt_subtree",
                "exempt_subtree": exempt_hit,
                "_norm": norm,
                "_exempt": True,
            })
            # 豁免行=用户已裁，三档均计入（此处直接累计，不走 meta tier 缓存）
            for t_name in ("conservative", "medium", "aggressive"):
                buckets = tiers.setdefault(
                    t_name, {"n_delete": 0, "bytes_delete": 0})
                buckets["n_delete"] += 1
                buckets["bytes_delete"] += size
            continue
        norm = _norm(run_dir)
        # 祖先链保护判定（指针优先、名字启发次之；整目录保留语义）
        chain_reason = _chain_protected(run_dir, root, pointer_hits)
        if chain_reason is not None:
            keep_reasons[chain_reason] = keep_reasons.get(chain_reason, 0) + 1
            continue
        _dir_info(norm, run_dir)  # 填目录级 tier 缓存（tiers 统计用）
        if _dir_recent(run_dir, _meta_file(run_dir), min_age_h, now):
            keep_reasons["recent_activity"] = \
                keep_reasons.get("recent_activity", 0) + 1
            continue
        try:
            rel_run = run_dir.relative_to(root).as_posix()
        except ValueError:
            rel_run = run_dir.as_posix()
        campaign = rel_run.split("/", 1)[0]
        sort_key = _run_sort_key(run_dir, _meta_file(run_dir))
        campaign_runs.setdefault(campaign, []).append((sort_key, norm))
        delete_rows.append({
            "path": h5.relative_to(root).as_posix(),
            "run_dir": rel_run,
            "size": size,
            "reason": "none",
            "_norm": norm,
        })

    # recent-n 豁免（按目录计，各档通用）：主循环按 h5 文件登记分组条目，
    # 同 run 目录（多 h5）须先按 norm 去重保序（目录 sort_key=各文件键的
    # 最大值）再取前 N——直接按条目切片会让同目录多文件重复占坑，豁免面
    # 静默缩水→破坏性删除超删（ge9 审查 P1-1；与 :517 注释/契约一致）。
    recent_exempt: set[str] = set()
    if keep_recent_n > 0:
        for _camp, items in campaign_runs.items():
            best: dict[str, tuple[str, str]] = {}
            for key, norm in items:
                if norm not in best or key > best[norm][0]:
                    best[norm] = (key, norm)
            ordered = sorted(best.values(), reverse=True)
            for _key, norm in ordered[:max(0, int(keep_recent_n))]:
                recent_exempt.add(norm)

    final_delete: list[dict[str, Any]] = []
    for row in delete_rows:
        norm = row.pop("_norm")
        exempt = row.pop("_exempt", False)
        if exempt:
            # 豁免行已在主循环累计三档（无 meta tier 可判）；豁免 norm 不进
            # campaign_runs 分组，recent-n 口径对豁免行天然不生效。
            final_delete.append(row)
            continue
        for t_name in ("conservative", "medium", "aggressive"):
            if norm in recent_exempt:
                continue
            if dir_cache[norm]["tier_ok"][t_name]:
                buckets = tiers.setdefault(
                    t_name, {"n_delete": 0, "bytes_delete": 0})
                buckets["n_delete"] += 1
                buckets["bytes_delete"] += row["size"]
        if norm not in recent_exempt and dir_cache[norm]["tier_ok"][tier]:
            final_delete.append(row)
    final_delete.sort(key=lambda r: r["path"])

    # golden 零改写断言（脚本断言，非人工抽查）：删除清单∩保护面前缀=∅
    protected_norms = set(pointer_hits)
    violations = [r["path"] for r in final_delete
                  if _norm_under(_norm(root / r["run_dir"]),
                                 protected_norms)]
    listed = final_delete[:max_rows]
    return ok_envelope(
        n_h5=n_h5,
        total_bytes=total_bytes,
        n_delete=len(final_delete),
        bytes_delete=sum(r["size"] for r in final_delete),
        delete=listed,
        delete_truncated=max(0, len(final_delete) - len(listed)),
        keep_reasons=keep_reasons,
        tiers=tiers,
        n_protected_dirs=len(protected_norms),
        protected_names=sorted(
            Path(p).name for p in list(protected_norms)[:200]),
        golden_rewrite_audit={"n_protected_dirs": len(protected_norms),
                              "violations": violations},
        keep_recent_n=int(keep_recent_n),
        min_age_h=float(min_age_h),
        exempt_subtrees=exempt_echo,
        **base)


def _exempt_hit(rel_path: str,
                exempt_map: dict[str, str]) -> str | None:
    """相对路径是否落在豁免子树内（最长前缀命中），命中返回子树 rel 名。"""
    best: str | None = None
    for _norm_key, rel_name in exempt_map.items():
        hit = rel_path == rel_name or rel_path.startswith(rel_name + "/")
        if hit and (best is None or len(rel_name) > len(best)):
            best = rel_name
    return best


def apply_h5_retention(
    plan: dict[str, Any],
    *,
    manifest_path: str | Path,
    runs_root: str | Path | None = None,
    operation_commit: str | None = None,
) -> dict[str, Any]:
    """执行 h5 删除（**破坏性**——CLI --apply 且 XD-5 互锁后才可达本函数）。

    白名单式点名删除（规则 3：逐路径点名，绝无通配 rm）；删除前重扫
    golden 零改写断言（删除清单∩保护面=∅，违反即整体拒绝零删）；manifest
    逐条记 {path, run_dir, size, reason, deleted_at, operation_commit}
    （湖删减可审计，spec §5.2①）。
    """
    root = Path(runs_root) if runs_root is not None \
        else Path(str(plan.get("runs_root") or "."))
    base: dict[str, Any] = {"runs_root": str(root),
                            "manifest_path": str(manifest_path)}
    rows = plan.get("delete")
    if not isinstance(rows, list):
        return error_envelope(["plan 无 delete 清单（先 plan_h5_retention）"],
                              **base)
    audit = plan.get("golden_rewrite_audit") or {}
    if audit.get("violations"):
        return error_envelope(
            ["golden 零改写断言失败（删除清单命中保护面，零删拒绝）: "
             + "; ".join(str(v) for v in audit["violations"][:10])],
            **base)
    commit = operation_commit if operation_commit is not None \
        else _git_head_short(_repo_root_guess())
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    n_deleted = 0
    bytes_freed = 0
    for row in rows:
        rel = str(row.get("path") or "")
        target = root / rel
        if not target.is_file():
            errors.append(f"删除目标不存在（跳过）: {rel}")
            continue
        # 双保险：删除前再验祖先链保护（plan 可能被篡改/过期）
        run_dir = _nearest_meta_dir(target, root)
        if run_dir is None:
            # 二次保护（审查 P2-2，2026-10-05）：plan→apply 窗口内 meta 消失
            # =在跑/半途嫌疑（#144 no_meta_inflight 同口径：任何档不可删）
            errors.append(f"删除目标 meta 在 plan 后消失（#144 在跑嫌疑，拒绝）: {rel}")
            continue
        if _chain_protected(run_dir, root, extract_pointer_dirs(root)) \
                is not None:
            errors.append(f"删除目标命中保护面（拒绝）: {rel}")
            continue
        # 二次保护补全：近期活动资格重验（与 plan 同判据 min_age，漂移即拒）
        if _dir_recent(run_dir, _meta_file(run_dir), 24.0, time.time()):
            errors.append(f"删除目标资格漂移（min_age 内新近活动，拒绝）: {rel}")
            continue
        try:
            size = target.stat().st_size
            target.unlink()
        except OSError as exc:
            errors.append(f"{rel}: 删除失败 {exc}")
            continue
        n_deleted += 1
        bytes_freed += size
        entries.append({
            "path": rel, "run_dir": str(row.get("run_dir") or ""),
            "size": size, "reason": str(row.get("reason") or "none"),
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "operation_commit": commit,
        })
    manifest = {
        "format": "rfauto-lake-h5-compact-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs_root": str(root),
        "tier": str(plan.get("tier") or ""),
        "n_entries": len(entries),
        "operation_commit": commit,
        "entries": entries,
    }
    mpath = Path(manifest_path)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    result: dict[str, Any] = {
        "n_deleted": n_deleted, "bytes_freed": bytes_freed, **base}
    if errors:
        return error_envelope(errors, **result)
    return ok_envelope(errors=[], **result)
