"""lake_compact_service —— RB-WN-1 湖语义压缩三件套（W3-A，sa_specs2 §五）。

三件（spec §5.2 逐件）：

① **h5 白名单保留策略**：``plan_h5_retention`` 纯读构建保留/删除/理由
分类三清单（推导式白名单——meta 无 run_type 字段（全湖实测零命中），
保留面只能从指针源与目录名启发推导）：锚注册表（knowledge/anchors.yaml）
路径指针→anchor_evidence；sim_ci golden 基线（knowledge/simci_baseline.yaml，
XD-5 pin 面）run_id→baseline_ref；tests/golden 等 golden 指针→golden_judged；
目录名启发（anchor/arb/arbitration/hfsswin/golden/review/gate）→
name_heuristic。理由=none 才可删（§5.4 宁保守——漏删只损失空间不损失证据）。
在跑/半途 run（无 meta，#144 形态）任何档都不可删；``--apply`` 真删由 CLI
层执行且缺省 dry-run。

② **et/ht 内容寻址去重**：原语在 infra/lake_blob_store（adapters 增量钩子
共用，分层契约），本模块给全湖 plan（纯读扫描+hash 分组统计）与 apply 包装
（受保护面零触碰）。

③ **sparams VF 有界摘要**：``sparams_summary`` 复用 core/macromodel 的
request_from_touchstone/fit_macromodel，产出 ``sparams.vf.json``
（{schema_version, n_poles, poles, residues, d_coeff, freq_band,
linf_error_linear, linf_error_db, rms_error, fidelity_class,
passivity_state, provenance}）。误差界是摘要组成部分（铁律 7 变体）：
L∞_linear ≤ 5e-3（≈dB 域 ≤0.05dB，#339 对拍门口径）→ lossless_equivalent；
超界如实标 bounded_lossy 带 linf 值——**不带误差界的摘要不落盘**。摘要
单激励部分矩阵只对已测元素（#314 掩码口径）计误差，零填充元素不进拟合
误差裁判；原 csv 不删（F3 冷压层处置），摘要=检索加速面非替代面。
消费面：lake index ``vf_summary`` 列（lake_service 单源）+ ``read_sparams_
summary``/``s_model_from_summary`` 零解压读面。

**golden 零改写红线（#325）**：本模块对受保护面（指针源命中目录+启发命中
目录+在跑 run）零写零替——dry-run 纯读；apply 只处理删除清单点名文件（白
名单式点名删除，规则 3），且 golden_rewrite_audit 钉"删除清单∩保护面=∅"。

**真湖放量口径（W3-A criteria 预声明）**：真实压缩/删除/迁移等破坏性动作
绝不自动执行——CLI 缺省 dry-run，--apply 需 XD-5 golden 基线已 pin 互锁
（sim_ci_service.default_baseline_path 在档且 schema 合法）。

无 __all__：公开 API 快照（DP-17）按 __all__ 登记，本件保持无 __all__ 即
不入快照（共享计数面零碰）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# ---------------------------------------------------------------------------
# 共用：runs 树遍历与保护面
# ---------------------------------------------------------------------------

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

#: meta 文件名（lake_service._META_NAMES 同口径，就地重复以免跨模块私引）
_META_NAMES = ("meta.json", "run_meta.json")

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


def _meta_file(run_dir: Path) -> Path | None:
    for name in _META_NAMES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _norm(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _git_head_short(repo: str | Path | None = None) -> str:
    """当前 HEAD 短 SHA（best-effort #105；失败空串不抛穿）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo) if repo else None)
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 and sha else ""
    except Exception:
        return ""


def _repo_root_guess() -> Path:
    return Path(__file__).resolve().parents[3]


def _dir_size_bytes(run_dir: Path) -> int:
    total = 0
    for current, _dirs, filenames in os.walk(run_dir):
        for name in filenames:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                continue
    return total


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

    # recent-n 豁免（按目录计，各档通用）
    recent_exempt: set[str] = set()
    if keep_recent_n > 0:
        for _camp, items in campaign_runs.items():
            items.sort(reverse=True)
            for _key, norm in items[:max(0, int(keep_recent_n))]:
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


def _norm_under(norm: str, protected_norms: set[str]) -> bool:
    """norm 是否命中保护集（精确相等或位于某保护目录之下）。"""
    return any(norm == p or norm.startswith(p.rstrip(os.sep) + os.sep)
               for p in protected_norms)


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


# ---------------------------------------------------------------------------
# ①b h5 保留策略的可逆执行面（W6-G 用户豁免放量：blob 化+manifest 审计，
#    禁裸删——同卷 move 进内容寻址 blob store，观察窗内可逐条回填恢复）
# ---------------------------------------------------------------------------

#: 可逆 compact manifest 格式标识（schema 演进锚）
REVERSIBLE_MANIFEST_FORMAT = "rfauto-lake-h5-compact-reversible-v1"

#: h5 在 blob store 内的 kind 目录（与 et/ht 同布局惯例：{kind}/<sha256 前 16>）
H5_BLOB_KIND = "h5"

#: 缺省观察窗天数（W6-G 用户裁决：30 天观察窗后 purge 才落物理释放）
DEFAULT_OBSERVATION_DAYS = 30


def _blob_path_for(store: Path, digest: str) -> Path:
    return store / H5_BLOB_KIND / digest[:16]


def _move_into_blob(target: Path, blob: Path, digest: str) -> tuple[str, str | None]:
    """把 target 原子移入 blob 位（同卷 rename 零拷贝；数据零丢失时序）。

    返回 (mode, error)：mode ∈ moved / dedup_existing / copied；error 非 None
    表示 target 原样保留未动。blob 已存在（同内容寻址命中）时只核 size 后
    删原路径——内容寻址 blob 视为不可变，绝不覆盖。
    """
    from rfauto.infra.lake_blob_store import sha256_of_file

    t_size = target.stat().st_size
    if blob.exists():
        try:
            b_size = blob.stat().st_size
        except OSError as exc:
            return "kept", f"blob 不可读（保留原样）: {exc}"
        if b_size != t_size:
            return "kept", (f"blob 与目标 size 不符（疑似哈希碰撞/损坏，"
                            f"保留原样不覆盖）: {blob}")
        try:
            target.unlink()
            return "dedup_existing", None
        except OSError as exc:
            return "kept", f"原路径移除失败: {exc}"
    blob.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(target, blob)
        return "moved", None
    except OSError:
        # 跨卷兜底：拷贝到临时名 → sha 复核 → 原子就位 → 删原路径
        tmp = blob.with_name(blob.name + ".tmp")
        try:
            shutil.copyfile(target, tmp)
            if sha256_of_file(tmp) != digest:
                tmp.unlink(missing_ok=True)
                return "kept", "跨卷拷贝 sha 复核不符（保留原样）"
            os.replace(tmp, blob)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            return "kept", f"跨卷拷贝失败（保留原样）: {exc}"
        try:
            target.unlink()
            return "copied", None
        except OSError as exc:
            return "kept", f"拷贝就位后原路径移除失败: {exc}"


def apply_h5_retention_reversible(
    plan: dict[str, Any],
    *,
    manifest_path: str | Path,
    runs_root: str | Path | None = None,
    blob_store: str | Path | None = None,
    operation_commit: str | None = None,
    min_age_h: float = 24.0,
    observation_days: int = DEFAULT_OBSERVATION_DAYS,
) -> dict[str, Any]:
    """h5 保留策略的**可逆**执行（W6-G 用户豁免放量面；禁裸删）。

    与 ``apply_h5_retention``（unlink 直删）不同：逐文件 sha256 → 同卷
    move 进内容寻址 blob store（``<store>/h5/<sha256 前 16>``）→ manifest
    逐条审计（相对路径+sha+blob 映射）。run 目录树即时缩容（bytes_freed
    与 plan 对账），物理空间在观察窗结束 purge 后落全量释放（30 天观察窗
    注记写进 manifest：回填路径+恢复/清退命令一行）。恢复=``restore_h5_
    from_manifest``（dry-run 可逐条 sha 回放核验）；清退=``purge_blobs_
    from_manifest``。

    安全面（与直删版同源加强）：删除清单∩保护面=∅ 断言（违反零动）；
    豁免行二次核验（豁免子树标记+子树包含关系+指针/名字保护链+min_age
    新近）；meta 行保留 meta 在档复核。blob 视为不可变，同内容二次命中
    只删原路径不覆盖（dedup_existing 如实记 mode）。
    """
    from rfauto.infra.lake_blob_store import blob_store_root, sha256_of_file

    root = Path(runs_root) if runs_root is not None \
        else Path(str(plan.get("runs_root") or "."))
    root = root.resolve()
    base: dict[str, Any] = {"runs_root": str(root),
                            "manifest_path": str(manifest_path)}
    rows = plan.get("delete")
    if not isinstance(rows, list):
        return error_envelope(["plan 无 delete 清单（先 plan_h5_retention）"],
                              **base)
    audit = plan.get("golden_rewrite_audit") or {}
    if audit.get("violations"):
        return error_envelope(
            ["golden 零改写断言失败（删除清单命中保护面，零动拒绝）: "
             + "; ".join(str(v) for v in audit["violations"][:10])],
            **base)
    plan_exempt = plan.get("exempt_subtrees") or []
    store = Path(blob_store) if blob_store is not None \
        else blob_store_root(root)
    store_norm = _norm(store)
    commit = operation_commit if operation_commit is not None \
        else _git_head_short(_repo_root_guess())
    pointers = extract_pointer_dirs(root)
    now = time.time()
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    n_moved = 0
    n_dedup = 0
    bytes_freed = 0
    bytes_retained = 0
    applied_at = datetime.now(timezone.utc)
    try:
        obs_days = max(0, int(observation_days))
    except (TypeError, ValueError):
        obs_days = DEFAULT_OBSERVATION_DAYS
    purge_after = applied_at + timedelta(days=obs_days)
    mtext = str(manifest_path)
    purge_date = purge_after.date().isoformat()

    def _flush_manifest() -> None:
        """崩溃安全：每条 move 落地即重写 manifest（path→blob 映射不断链）。"""
        manifest = {
            "format": REVERSIBLE_MANIFEST_FORMAT,
            "created_at": applied_at.isoformat(),
            "runs_root": str(root),
            "tier": str(plan.get("tier") or ""),
            "n_entries": len(entries),
            "bytes_freed": bytes_freed,
            "bytes_retained": bytes_retained,
            "operation_commit": commit,
            "blob_store_rel": ".blob_store",
            "exempt_subtrees": list(plan_exempt),
            "observation_window": {
                "days": obs_days,
                "applied_at": applied_at.isoformat(),
                "purge_after": purge_date,
                "backfill_path": "runs/.blob_store/h5",
                "restore_command": (
                    ".venv\\Scripts\\python.exe -c \"from rfauto.service."
                    "lake_compact_service import restore_h5_from_manifest; "
                    f"print(restore_h5_from_manifest(r'{mtext}'))\""),
                "purge_command": (
                    ".venv\\Scripts\\python.exe -c \"from rfauto.service."
                    "lake_compact_service import purge_blobs_from_manifest; "
                    f"print(purge_blobs_from_manifest(r'{mtext}'))\""),
                "note": (f"可逆豁免放量（禁裸删）：内容已 blob 化于 "
                         f"runs/.blob_store/h5，观察窗 {obs_days} 天内可按 "
                         "restore_command 逐条回填；窗满（" + purge_date
                         + "）无回归再执行 purge_command 落物理释放。"),
            },
            "entries": entries,
        }
        mpath = Path(manifest_path)
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    for row in rows:
        rel = str(row.get("path") or "")
        target = root / rel
        if not target.is_file():
            errors.append(f"目标不存在（跳过）: {rel}")
            continue
        # 写面前收口：目标必须真在 runs 根下（防清单被篡改/路径穿越）
        if not _norm(target).startswith(_norm(root) + os.sep):
            errors.append(f"目标越出 runs 根（拒绝）: {rel}")
            continue
        exempt_hit = str(row.get("exempt_subtree") or "")
        if exempt_hit:
            # 豁免行二次核验：标记必须与 plan 回显一致 + 路径确在子树内
            if exempt_hit not in plan_exempt:
                errors.append(f"豁免子树标记与 plan 回显不符（拒绝）: {rel}")
                continue
            if not (rel == exempt_hit
                    or rel.startswith(exempt_hit + "/")):
                errors.append(f"目标越出豁免子树（拒绝）: {rel}")
                continue
            if _chain_protected(target.parent, root, pointers) is not None:
                errors.append(f"目标命中保护链（拒绝）: {rel}")
                continue
            try:
                if now - target.stat().st_mtime < max(0.0, min_age_h) * 3600:
                    errors.append(f"目标资格漂移（min_age 内新近，拒绝）: {rel}")
                    continue
            except OSError as exc:
                errors.append(f"{rel}: 不可读 {exc}")
                continue
        else:
            # meta 行：meta 在档复核（plan→apply 窗口内消失=在跑嫌疑 #144）
            if _nearest_meta_dir(target, root) is None:
                errors.append(
                    f"删除目标 meta 在 plan 后消失（#144 在跑嫌疑，拒绝）: {rel}")
                continue
            if _chain_protected(root / str(row.get("run_dir") or rel),
                                root, pointers) is not None:
                errors.append(f"删除目标命中保护面（拒绝）: {rel}")
                continue
        digest = sha256_of_file(target)
        if digest is None:
            errors.append(f"sha256 不可读（跳过）: {rel}")
            continue
        blob = _blob_path_for(store, digest)
        if not _norm(blob).startswith(store_norm + os.sep):
            errors.append(f"blob 位越出 store（拒绝）: {rel}")
            continue
        size = target.stat().st_size
        mode, err = _move_into_blob(target, blob, digest)
        if err is not None:
            errors.append(f"{rel}: {err}")
            continue
        try:
            if blob.stat().st_size != size:
                raise OSError("move 后 size 复核不符")
        except OSError as exc:
            errors.append(f"{rel}: move 后复核失败 {exc}")
            continue
        if mode == "dedup_existing":
            n_dedup += 1
        else:
            n_moved += 1
        bytes_freed += size
        bytes_retained += size
        entries.append({
            "path": rel, "run_dir": str(row.get("run_dir") or ""),
            "size": size, "sha256": digest,
            "blob": f"{H5_BLOB_KIND}/{digest[:16]}",
            "mode": mode, "reason": str(row.get("reason") or "none"),
            "exempt_subtree": exempt_hit or None,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "operation_commit": commit,
        })
        _flush_manifest()
    _flush_manifest()  # 收尾兜底（空清单/尾条目后状态一致）
    result: dict[str, Any] = {
        "n_deleted": n_moved + n_dedup,
        "n_moved": n_moved,
        "n_dedup_existing": n_dedup,
        "bytes_freed": bytes_freed,
        "bytes_retained": bytes_retained,
        "blob_store": str(store),
        "purge_after": purge_after.date().isoformat(),
        **base}
    if errors:
        return error_envelope(errors, **result)
    return ok_envelope(errors=[], **result)


def _resolve_manifest_targets(
    manifest: dict[str, Any],
    manifest_path: Path,
    runs_root: str | Path | None,
    out: dict[str, Any],
) -> tuple[Path, Path] | None:
    """manifest → (runs 根, blob store 根) 解析；失败时 errors 已记账。"""
    rel_store = str(manifest.get("blob_store_rel") or ".blob_store")
    base_str = str(runs_root) if runs_root is not None \
        else str(manifest.get("runs_root") or ".")
    base = Path(base_str)
    if not base.is_dir():
        out["errors"].append(
            f"runs 根不可达（传 runs_root 或自仓根运行）: {base}")
        return None
    return base, base / rel_store


def restore_h5_from_manifest(
    manifest_path: str | Path,
    *,
    runs_root: str | Path | None = None,
    target_root: str | Path | None = None,
    verify: bool = True,
    dry_run: bool = False,
    max_errors: int = 50,
) -> dict[str, Any]:
    """按可逆 compact manifest 回填/核验（恢复面；缺省 dry_run=False 真回填）。

    ``dry_run=True``：零写面——逐条核 blob 在档 +（verify=True 时）blob sha
    与 manifest 逐位一致（判据"manifest 逐条 sha 可回放"的本体）。
    ``target_root`` 给出时回填到新目录（模拟重建，不触碰原湖——测试面口径）；
    原位回填时 dest 已在且 sha 一致记 already_restored，不符记 error 拒绝
    覆盖。逐条失败记 error 继续（如实报告，不静默丢条目）。
    """
    from rfauto.infra.lake_blob_store import sha256_of_file

    out: dict[str, Any] = {"ok": False, "n_entries": 0, "n_verified": 0,
                           "n_restored": 0, "n_already": 0,
                           "n_missing_blob": 0, "n_sha_mismatch": 0,
                           "n_skipped": 0, "dry_run": bool(dry_run),
                           "errors": []}
    mpath = Path(manifest_path)
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["errors"].append(f"manifest 读取/解析失败: {exc}")
        return out
    if not isinstance(manifest, dict) \
            or manifest.get("format") != REVERSIBLE_MANIFEST_FORMAT:
        out["errors"].append(
            f"manifest 格式不符（期望 {REVERSIBLE_MANIFEST_FORMAT}）")
        return out
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        out["errors"].append("manifest 缺 entries 段")
        return out
    resolved = _resolve_manifest_targets(manifest, mpath, runs_root, out)
    if resolved is None:
        return out
    base, store = resolved
    if target_root is not None:
        base = Path(target_root)
    out["n_entries"] = len(entries)
    for entry in entries:
        rel = str(entry.get("path") or "")
        digest = str(entry.get("sha256") or "")
        blob_rel = str(entry.get("blob") or "")
        if not rel or not digest:
            out["n_skipped"] += 1
            out["errors"].append(f"条目缺 path/sha256: {entry!r}"[:200])
            continue
        blob = store / blob_rel if blob_rel             else _blob_path_for(store, digest)
        if not blob.is_file():
            out["n_missing_blob"] += 1
            out["errors"].append(f"blob 缺失: {rel}（{blob.name}）")
            continue
        if verify:
            actual = sha256_of_file(blob)
            if actual is None:
                out["n_skipped"] += 1
                out["errors"].append(f"blob 不可读: {rel}")
                continue
            if actual != digest:
                out["n_sha_mismatch"] += 1
                out["errors"].append(f"blob sha 与 manifest 不符: {rel}")
                continue
        out["n_verified"] += 1
        if dry_run:
            continue
        dest = base / rel
        try:
            if dest.is_file():
                cur = sha256_of_file(dest)
                if cur == digest:
                    out["n_already"] += 1
                    continue
                out["n_skipped"] += 1
                out["errors"].append(
                    f"现文件存在且 sha 不符（拒绝覆盖）: {rel}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(blob, dest)
            except OSError:
                shutil.copyfile(blob, dest)
        except OSError as exc:
            out["n_skipped"] += 1
            if len(out["errors"]) < max_errors:
                out["errors"].append(f"{rel}: 回填失败 {exc}")
            continue
        back = sha256_of_file(dest)
        if back != digest:
            out["n_skipped"] += 1
            out["errors"].append(f"{rel}: 回填后 sha 复核不符")
            continue
        out["n_restored"] += 1
    shape_ok = (out["n_missing_blob"] == 0 and out["n_sha_mismatch"] == 0
                and not any("失败" in e or "不符" in e or "缺" in e
                            for e in out["errors"]))
    out["ok"] = bool(shape_ok and out["n_verified"] == out["n_entries"]
                     and (dry_run or
                          out["n_restored"] + out["n_already"]
                          == out["n_entries"]))
    return out


def purge_blobs_from_manifest(
    manifest_path: str | Path,
    *,
    runs_root: str | Path | None = None,
    max_errors: int = 50,
) -> dict[str, Any]:
    """观察窗满后的 blob 清退（**破坏性**——物理释放落点；用户窗显式执行）。

    仅删 manifest 点名 blob（内容寻址位，逐条核在 store 目录内），run
    目录树零触碰。 Returns: {"ok", "n_entries", "n_purged",
    "bytes_released", "n_missing", "errors"}。
    """
    out: dict[str, Any] = {"ok": False, "n_entries": 0, "n_purged": 0,
                           "bytes_released": 0, "n_missing": 0, "errors": []}
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["errors"].append(f"manifest 读取/解析失败: {exc}")
        return out
    if not isinstance(manifest, dict) \
            or manifest.get("format") != REVERSIBLE_MANIFEST_FORMAT:
        out["errors"].append(
            f"manifest 格式不符（期望 {REVERSIBLE_MANIFEST_FORMAT}）")
        return out
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        out["errors"].append("manifest 缺 entries 段")
        return out
    resolved = _resolve_manifest_targets(manifest, Path(manifest_path),
                                         runs_root, out)
    if resolved is None:
        return out
    _base, store = resolved
    store_norm = _norm(store)
    out["n_entries"] = len(entries)
    for entry in entries:
        digest = str(entry.get("sha256") or "")
        blob_rel = str(entry.get("blob") or "")
        blob = (store / blob_rel) if blob_rel else _blob_path_for(store, digest)
        if not _norm(blob).startswith(store_norm + os.sep):
            out["errors"].append(f"blob 位越出 store（拒绝）: {blob_rel}")
            continue
        try:
            size = blob.stat().st_size
        except OSError:
            out["n_missing"] += 1
            continue
        try:
            blob.unlink()
        except OSError as exc:
            if len(out["errors"]) < max_errors:
                out["errors"].append(f"{blob_rel}: 清退失败 {exc}")
            continue
        out["n_purged"] += 1
        out["bytes_released"] += size
    out["ok"] = not out["errors"]
    return out


# ---------------------------------------------------------------------------
# ② et/ht 去重的 service 包装（plan 纯读 / apply 走 infra 原语）
# ---------------------------------------------------------------------------

def _inflight_dir_norms(root: Path) -> set[str]:
    """完全无 meta 的子树目录集（在跑/半途 #144 形态，归一键）。

    口径：目录自身无 meta **且**子树内无任何 meta（全 inflight 子树）才
    入集——meta 容器战役（无 meta 但其下 run 点有 meta）不算 inflight，
    其已落盘 run 点的产物正常参与去重；run 点无 meta（#144 在跑形态）
    整子树跳过。根自身不计。
    """
    out: set[str] = set()
    root_norm = _norm(root)

    def visit(d: Path) -> bool:
        """返回子树是否完全无 meta；完全无 meta 的子树目录入 out。"""
        has_meta = _meta_file(d) is not None
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir()
                              and not p.name.startswith(".")
                              and p.name != "__pycache__")
        except OSError:
            children = []
        child_all_inflight = all(visit(c) for c in children)
        inflight = (not has_meta) and child_all_inflight
        if inflight and _norm(d) != root_norm:
            out.add(_norm(d))
        return inflight

    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for child in children:
        visit(child)
    return out


def plan_et_ht_dedup(
    runs_root: str | Path = "runs",
    *,
    min_age_h: float = 24.0,
    pointer_sources: list[tuple[str | Path, str]] | None = None,
) -> dict[str, Any]:
    """全湖 et/ht 去重规划（纯读：逐文件 sha256 分组统计，零写）。

    保护口径与 apply 同源（宁保守）：指针源命中面 + 在跑/半途（无 meta
    祖先 #144）+ mtime 距今不足 min_age_h 的文件，全部跳过并如实计数。

    Returns:
        dict: {"ok", "n_files", "total_bytes", "n_unique", "n_dup_files",
        "bytes_dup_total"（重复面字节，去重上限收益）, "n_protected",
        "n_inflight", "errors"}
    """
    from rfauto.infra.lake_blob_store import DEDUP_KINDS, sha256_of_file

    root = Path(runs_root).resolve()
    base: dict[str, Any] = {"runs_root": str(root)}
    if not root.is_dir():
        return error_envelope([f"runs 根不存在: {root}"], **base)
    protected = set(extract_pointer_dirs(root, pointer_sources).keys())
    inflight = _inflight_dir_norms(root)
    now = time.time()
    fresh_cut = max(0.0, min_age_h) * 3600.0
    store_norm = _norm(root / ".blob_store")
    groups: dict[str, int] = {}
    group_bytes: dict[str, int] = {}
    n_files = 0
    total_bytes = 0
    n_protected = 0
    n_fresh = 0
    errors: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames
                       if _norm(here / d) != store_norm]
        here_norm = _norm(here)
        skip_dir = here_norm in inflight or _norm_under(here_norm, inflight) \
            or here_norm in protected or _norm_under(here_norm, protected)
        for name in filenames:
            suffix = os.path.splitext(name)[1].lower().lstrip(".")
            if suffix not in DEDUP_KINDS:
                continue
            path = here / name
            if skip_dir:
                n_protected += 1
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if now - st.st_mtime < fresh_cut:
                n_fresh += 1
                continue
            digest = sha256_of_file(path)
            if digest is None:
                errors.append(f"sha256 不可读: {path}")
                continue
            n_files += 1
            total_bytes += st.st_size
            groups[digest] = groups.get(digest, 0) + 1
            group_bytes[digest] = st.st_size
    n_dup_files = sum(c - 1 for c in groups.values() if c > 1)
    bytes_dup = sum((c - 1) * group_bytes[d]
                    for d, c in groups.items() if c > 1)
    return ok_envelope(
        n_files=n_files, total_bytes=total_bytes, n_unique=len(groups),
        n_dup_files=n_dup_files, bytes_dup_total=bytes_dup,
        n_protected=n_protected, n_inflight_dirs=len(inflight),
        n_too_fresh=n_fresh,
        errors=errors[:50], **base)


def apply_et_ht_dedup(
    runs_root: str | Path = "runs",
    *,
    min_age_h: float = 24.0,
    manifest_path: str | Path | None = None,
    pointer_sources: list[tuple[str | Path, str]] | None = None,
) -> dict[str, Any]:
    """全湖 et/ht 去重执行（**破坏性**——CLI --apply 且 XD-5 互锁后可达）。

    受保护面零触碰：指针源命中目录 + 在跑/半途（无 meta 祖先，#144）+
    mtime 新近文件一律跳过（infra 层逐文件跳过+如实计数）。
    """
    from rfauto.infra.lake_blob_store import blob_store_root, dedup_tree_et_ht

    root = Path(runs_root).resolve()
    protected = set(extract_pointer_dirs(root, pointer_sources).keys())
    protected |= _inflight_dir_norms(root)
    result = dedup_tree_et_ht(
        root, blob_store_root(root), protected_norm=frozenset(protected),
        min_age_h=min_age_h, manifest_path=manifest_path)
    return result


# ---------------------------------------------------------------------------
# ③ sparams VF 有界摘要
# ---------------------------------------------------------------------------

#: 摘要 schema 版本（演进锚）
VF_SUMMARY_SCHEMA = "rfauto-sparams-vf-summary-v1"

#: 摘要文件名（run 目录内，与 sparams.csv 并排）
VF_SUMMARY_NAME = "sparams.vf.json"

#: lossless_equivalent 门槛（spec §5.3 判据 2：L∞_linear ≤5e-3 ≈ ≤0.05dB）
LINF_LOSSLESS_THRESHOLD = 5e-3


def _fit_request_from_sparams_csv(
    csv_path: Path,
) -> tuple[dict[str, Any], Any, Any, int] | None:
    """sparams.csv → fit_macromodel request 片段 + (freq, s, mask)。

    复用 health_service._parse_sparams_csv_masked（#314 掩码单源，零新解
    析器）；未测元素零填充进拟合输入（fit_macromodel 要求全矩阵），误差
    裁判只对掩码内元素计——部分矩阵语义见模块 docstring。坏 csv（loadtxt
    ValueError/OSError）同样 None（调用方零写面拒绝）。
    """
    from rfauto.service.health_service import _parse_sparams_csv_masked

    try:
        parsed = _parse_sparams_csv_masked(csv_path)
    except (OSError, ValueError):
        return None
    if parsed is None:
        return None
    freq, s, mask = parsed
    n = int(s.shape[1])
    request = {
        "freq_hz": [float(x) for x in freq],
        "s": [[[[float(v.real), float(v.imag)] for v in row] for row in mat]
              for mat in s],
        "z0": [50.0] * n,
        "n_ports": n,
        "source_path": str(csv_path),
        "spice_replay": False,
    }
    return request, freq, mask, n


def _rational_response(
    poles: list[list[float]],
    residues: list[list[list[float]]],
    d_coeff: list[list[list[float]]],
    freq_hz: Any,
    n_ports: int,
) -> Any:
    """存档系数 → 有理分式模型 S 矩阵重建（[nf, n, n] 复数）。

    口径=skrf VectorFitting.get_model_response（安装版实测逐行对照）：
    ``S_ij(s) = d_ij + Σ_k residues[i*n+j][k]/(s − poles[k])``，且**复数
    极点隐式带共轭项**（skrf 存 n_poles_cmplx 个单支复极点，响应求值时
    自动补 conj(residues)/（s−conj(poles))——非共轭对显式存储）；无比例项
    （fit_macromodel 全链 proportional=False）。与内核 model_response 的
    等价性由单测钉（W3-A test_w3_a_*.py，#118 独立回收口径）。
    """
    import numpy as np

    f = np.asarray(freq_hz, dtype=float).ravel()
    s = 2j * np.pi * f
    out = np.zeros((f.size, n_ports, n_ports), dtype=complex)
    poles_c = [complex(re_, im_) for re_, im_ in poles]
    for i in range(n_ports):
        for j in range(n_ports):
            resp = np.full(f.size, complex(d_coeff[i][j][0],
                                           d_coeff[i][j][1]), dtype=complex)
            beta = residues[i * n_ports + j]
            for k, pole in enumerate(poles_c):
                term = complex(beta[k][0], beta[k][1]) / (s - pole)
                if pole.imag == 0.0:
                    resp = resp + term
                else:
                    resp = resp + term + np.conjugate(
                        complex(beta[k][0], beta[k][1])) / (s - pole.conjugate())
            out[:, i, j] = resp
    return out


def s_model_from_summary(summary: dict[str, Any], freq_hz: Any) -> Any:
    """摘要 JSON → 模型 S 矩阵重建（冷层消费面：零 csv 解压零重拟合）。"""
    return _rational_response(
        summary.get("poles") or [],
        summary.get("residues") or [],
        summary.get("d_coeff") or [],
        freq_hz,
        int(summary.get("n_ports") or 0))


def sparams_summary(
    run_dir: str | Path,
    *,
    write: bool = True,
    fit_commit: str | None = None,
    order_ladder: list[tuple[int, int]] | None = None,
    rms_threshold_db: float = -60.0,
) -> dict[str, Any]:
    """run 目录 sparams.csv → VF 有界摘要 ``sparams.vf.json``（spec ③）。

    误差界为摘要组成部分（铁律 7 变体）：L∞/rms 只对已测元素（#314 掩码）
    计；linf ≤ LINF_LOSSLESS_THRESHOLD → fidelity_class=lossless_equivalent，
    否则 bounded_lossy 带 linf 值如实（深谷族不硬压，#370 教训的压缩版）。
    拟合失败/源不可解析 → error 信封且**零写面**（不带误差界的摘要不落盘）。
    ``rms_threshold_db`` 缺省 -60（比内核 SPICE 导出缺省 -40 深一档：本门
    是 L∞≤5e-3 口径，实测 -40dB rms 档 L∞ 峰可到 ~2e-2，阶梯需推进到更
    深档才进 lossless 界——合成回收实证，见 W3-A 单测 fixture）。

    Returns:
        dict: {"ok", "summary_path"?, "fidelity_class"?, "linf_error_linear"?,
        "rms_error"?, "n_poles"?, **errors?}——summary 正文即落盘 JSON。
    """
    import numpy as np

    from rfauto.core.macromodel import fit_macromodel

    rd = Path(run_dir)
    base: dict[str, Any] = {"run_dir": str(rd)}
    csv_path = rd / "sparams.csv"
    if not csv_path.is_file():
        return error_envelope([f"sparams.csv 不存在: {csv_path}"], **base)
    built = _fit_request_from_sparams_csv(csv_path)
    if built is None:
        return error_envelope([f"sparams.csv 不可解析: {csv_path}"], **base)
    request, freq, mask, n_ports = built
    if order_ladder:
        request["order_ladder"] = [(int(a), int(b))
                                   for a, b in order_ladder]
    request["rms_threshold_db"] = float(rms_threshold_db)
    # 部分矩阵（单激励零填充）不做无源化强制：零填充元素使全矩阵天然非
    # 无源，enforce 只会为迁就零元素扭曲已测元素的拟合（且 enforcement
    # 失败时残差反被恶化）；摘要=检索加速面，passivity_state 如实记录。
    if not bool(mask.all()):
        request["enforce_passivity"] = False
    try:
        fit = fit_macromodel(request)
    except Exception as exc:
        return error_envelope([f"VF 拟合失败（零写面）: "
                               f"{type(exc).__name__}: {exc}"], **base)

    s_raw = np.asarray(request["s"], dtype=float)
    s_orig = s_raw[..., 0] + 1j * s_raw[..., 1]  # [re,im] 嵌套 → 复数矩阵
    poles = fit.get("poles_rad_s") or []
    residues = fit.get("residues") or []
    d_coeff_flat = fit.get("constant_coeff") or []
    try:
        d_coeff = [[list(d_coeff_flat[i * n_ports + j])
                    for j in range(n_ports)] for i in range(n_ports)]
        s_model = _rational_response(poles, residues, d_coeff, freq, n_ports)
    except Exception as exc:
        return error_envelope([f"摘要重建失败（零写面）: {exc}"], **base)
    diff = np.abs(s_model - s_orig)
    linf_linear = float(diff[:, mask].max()) if mask.any() else float(np.max(diff))
    rms_linear = float(np.sqrt(np.mean(diff[:, mask] ** 2))) if mask.any() \
        else float(np.sqrt(np.mean(diff ** 2)))
    linf_db = float(20.0 * np.log10(max(linf_linear, 1e-12)))
    fidelity_class = ("lossless_equivalent"
                      if linf_linear <= LINF_LOSSLESS_THRESHOLD
                      else "bounded_lossy")
    passivity = fit.get("passivity") or {}
    after = passivity.get("after") or {}
    csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    commit = fit_commit if fit_commit is not None \
        else _git_head_short(_repo_root_guess())
    summary = {
        "schema_version": VF_SUMMARY_SCHEMA,
        "run_dir": str(rd),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_ports": int(n_ports),
        "n_points": int(np.asarray(freq).size),
        "n_poles": len(poles),
        "poles": poles,
        "residues": residues,
        "d_coeff": d_coeff,
        "freq_band": [float(np.asarray(freq).min()),
                      float(np.asarray(freq).max())],
        "linf_error_linear": linf_linear,
        "linf_error_db": linf_db,
        "rms_error": rms_linear,
        "linf_threshold_linear": LINF_LOSSLESS_THRESHOLD,
        "fidelity_class": fidelity_class,
        "partial_matrix": bool(not mask.all()),
        "n_measured_entries": int(mask.sum()),
        "n_total_entries": int(mask.size),
        "passivity_state": {
            "passive_in_band": after.get("passive_in_band"),
            "sigma_max_in_band": after.get("sigma_max_in_band"),
            "enforced": passivity.get("enforced"),
            "enforce_error": passivity.get("enforce_error"),
        },
        "provenance": {
            "fit_commit": commit,
            "source_csv_sha256": csv_sha,
            "source_path": str(csv_path),
            "kernel": "core.macromodel.fit_macromodel（request_from_"
                      "touchstone 同族链；本摘要走 sparams.csv 掩码面）",
        },
    }
    out_path = rd / VF_SUMMARY_NAME
    if write:
        # 落盘前断言误差界在档（不带误差界的摘要不落盘——结构性守卫；
        # NaN 不满足 >= 0 即拒）
        if not (linf_linear >= 0.0):
            return error_envelope(["误差界异常（NaN?），拒绝落盘"], **base)
        out_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return ok_envelope(
        summary_path=str(out_path),
        fidelity_class=fidelity_class,
        linf_error_linear=linf_linear,
        linf_error_db=linf_db,
        rms_error=rms_linear,
        n_poles=len(poles),
        summary=summary if not write else None,
        **base)


def read_sparams_summary(run_dir: str | Path) -> dict[str, Any]:
    """读 run 目录摘要（零解压读面；缺/坏如实 ok=False）。"""
    path = Path(run_dir) / VF_SUMMARY_NAME
    data = _read_json_object(path)
    if data is None:
        return error_envelope([f"摘要不存在或不可解析: {path}"],
                              run_dir=str(run_dir))
    return ok_envelope(summary=data, summary_path=str(path),
                       run_dir=str(run_dir))


def plan_sparams_summaries(
    runs_root: str | Path = "runs",
    *,
    max_rows: int = 200,
) -> dict[str, Any]:
    """摘要生成机会盘点（**纯读**——真湖生成等用户窗，W3-A criteria）。

    资格口径：sparams.csv 在档 + meta 在档 + 尚无 sparams.vf.json。
    """
    root = Path(runs_root).resolve()
    base: dict[str, Any] = {"runs_root": str(root)}
    if not root.is_dir():
        return error_envelope([f"runs 根不存在: {root}"], **base)
    eligible: list[dict[str, Any]] = []
    n_csv = 0
    n_existing = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if "sparams.csv" in filenames:
            n_csv += 1
            if VF_SUMMARY_NAME in filenames:
                n_existing += 1
                continue
            if _meta_file(here) is None:
                continue
            eligible.append({"path": here.relative_to(root).as_posix()})
    listed = eligible[:max_rows]
    return ok_envelope(
        n_sparams_csv=n_csv, n_summary_existing=n_existing,
        n_eligible=len(eligible), eligible=listed,
        eligible_truncated=max(0, len(eligible) - len(listed)),
        note="真湖摘要生成属写面（run 目录内新增文件），等用户窗放量；"
             "本盘点纯读零写", **base)
