"""ui_service.cache —— 端点扫描缓存三层原语 + registry 单源索引层/自愈回填（aurora72 A2-D / R8-ENG2）。

自 ui_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁；本域是包内叶子（runs_recipes/views/insights 从这里单向导入，包内零环）。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.ui_scan_cache import (  # T1 解环：缓存原语叶化（定义体在 ui_scan_cache）
    _UI_CACHE_OFF_VALUES,
    _UiScanCache,
)
from rfauto.service.ui_scan_cache import (
    _UI_SCAN_TTL_S as _UI_SCAN_TTL_S,
)
from rfauto.service.ui_scan_cache import (
    _ui_cache_enabled as _ui_cache_enabled,
)

RUNS_DIR = Path("runs")

_LOG = logging.getLogger(__name__)


# ═══ runs/ 全表扫端点缓存（aurora72 A2-D；R8 发现 1）═════════════════════════
#
# calibration_runs / cross_fidelity_view / list_reports / pareto_runs /
# field_runs 五端点此前每请求对 runs/（实测 2246 目录）逐 run stat+读 JSON，
# field_runs 另逐 .h5 开 h5py 探测（真树冷跑实测 9.3s），零缓存。本节三层
# 进程内缓存：
#
#   1. 目录清单（_DIR_LISTING_CACHE）：runs/ 顶层 (Path, is_dir) 升序快照；
#   2. 文件级（_JSON_FILE_CACHE 的 JSON 读 / _H5_PROBE_CACHE 的 h5 探测 /
#      _RUN_SCAN_CACHE 的 per-run 场 dump 清单与 trials 计数）：签名含
#      (mtime_ns, size) 或目录 mtime，新增/删除/就地改写即刻失效；
#   3. 端点快照（_SNAPSHOT_CACHE）：端点全量 payload（limit 切片前），
#      签名=_runs_fingerprint()（单次 scandir；Windows 上 DirEntry 元数据
#      免系统调用，2246 目录 ~2ms）。
#
# 失效语义（保守优先，宁多扫不多旧）：
#   - 顶层结构变化（run 目录/顶层文件 新增、删除、改名）→ 指纹里的条目
#     名集合变化，**即刻失效**（枚举反映当前条目，不依赖 mtime）；
#   - 嵌套产物变化（既有 run 内新落 gate.json、trials/*.json、fdtd/*.h5）：
#     依赖该 run 目录 mtime 进入指纹——**实测 NTFS 目录 mtime 懒更新**
#     （新建条目后数十 ms 内 stat 值可能不动，racy），故此路径不作为
#     硬保证；硬保证=TTL 兜底（快照层+per-run 层各 ≤TTL，嵌套产物最坏
#     可见时延 ≈2×_UI_SCAN_TTL_S）；
#   - 命中=「未超龄 且 签名逐位相等」双条件缺一即重扫；签名不可得
#     （runs/ 不存在等 stat/scandir OSError）→ 直通重扫且不落缓存。
#   - env RFAUTO_UI_CACHE=0|false|off|no → 全部直通（每请求实时原行为）。
# 观测（#105 best-effort）：各缓存命中/miss 计数 + miss 时 INFO 日志（含
# 耗时），_ui_cache_stats() 可编程读取。
#
# registry.sqlite 接线（R8-ENG2，2026-10-13；地基=registry_runs_query 单入口
# + runs 湖回填 1799 行 + scripts/registry_backfill.py --check 落后度门）：
# A2-D 时点"只做缓存不接 sqlite"的评估结论基于当时库面 1779/2247 行且无
# 回填——地基补齐后本节把五端点接到 registry 单源：registry 行（经
# registry_runs_query 只读单入口）覆盖盘面全部判真 run 点（covered 态）时，
# 条目的 model/adapter 直接取行、**零 meta.json 读**；registry 缺行（新落
# run 未回填/库缺席/库损坏）→ 该次快照整体回退 A2-D 全扫路径（字节等价）
# 并节流触发自愈回填（缺行行 INSERT OR IGNORE，与 backfill 同口径），回填
# 落库 → registry mtime 变化 → 指纹失效 → 下次快照自动升级 covered 态。
# 指纹=（registry 文件 mtime_ns+size, runs/ 顶层目录名集），指纹不变直接
# 命中索引（报告的"mtime/目录数"缓存语义；目录名集比纯计数多抓改名）。
# 保真规则（防行集/字段级语义漂移）：库行仅在 model/adapter 均非空时参与
# 服务（空值/B 类 no_meta_run 行恒回退文件读，None/"" 语义与文件面逐位
# 一致）；gate.json 字段/报告存在性/trials 计数/场 dump 仍由文件面缓存供
# 给（库内无此信息）。env RFAUTO_UI_REGISTRY=0|false|off|no → registry 零
# 查询、五端点恒走全扫路径（"改造前" A/B 计时与逃生口）。

#: 缓存直通开关的 env 关闭取值（大小写不敏感；其余取值含未设=启用）
#: 快照/清单缓存存活上限（秒）：签名未变也到期重扫，兜底"嵌套产物变化 +
#: NTFS 目录 mtime 懒更新"盲区（宁多扫不多旧；嵌套最坏可见时延≈2×TTL，
#: 快照层与 per-run 层各 ≤TTL）


_DIR_LISTING_CACHE = _UiScanCache("dir_listing")
_JSON_FILE_CACHE = _UiScanCache("json_file")
_H5_PROBE_CACHE = _UiScanCache("h5_probe")
_RUN_SCAN_CACHE = _UiScanCache("run_scan")
_SNAPSHOT_CACHE = _UiScanCache("snapshot")
#: registry 单源索引缓存（R8-ENG2；行为见下方 registry 索引层注记）
_REG_INDEX_CACHE = _UiScanCache("reg_index")

#: 全部扫描缓存单源清单（stats/clear 共用；新缓存入此处即被观测与隔离覆盖）
_UI_SCAN_CACHES = (_DIR_LISTING_CACHE, _JSON_FILE_CACHE, _H5_PROBE_CACHE,
                   _RUN_SCAN_CACHE, _SNAPSHOT_CACHE, _REG_INDEX_CACHE)


def _ui_cache_stats() -> dict[str, Any]:
    """六缓存命中/miss 计数（观测面；#105 best-effort，测试与运维读）。"""
    return {
        c.name: c.stats()
        for c in _UI_SCAN_CACHES
    }


def _ui_scan_cache_clear() -> None:
    """清空全部扫描缓存（测试隔离/运维排查用；不影响计数）。"""
    for c in _UI_SCAN_CACHES:
        c._store.clear()


def _runs_dir_key() -> str:
    """缓存键的 runs/ 根标识（cwd/chdir 与 RUNS_DIR monkeypatch 隔离）。"""
    return os.path.normcase(str(Path(RUNS_DIR).absolute()))


def _file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size)；stat 失败→None（直通不缓存）。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _runs_fingerprint(
    root: Path | str | None = None,
) -> tuple[int, tuple[tuple[str, int], ...], tuple[str, ...]] | None:
    """runs/ 变化指纹：顶层 mtime + 逐 run 目录 mtime + 顶层文件名（单次 scandir）。

    Windows 上 DirEntry.stat/is_dir(follow_symlinks=False) 直接用目录枚举
    自带元数据、零额外系统调用（2246 目录实测 ~2ms）。顶层条目（run 目录
    与顶层文件）的新增/删除/改名改变条目名集合 → 指纹变化 → 快照即刻
    失效（枚举反映当前条目，不依赖 mtime）；嵌套产物变化只能靠该 run
    目录 mtime（NTFS 懒更新，racy）+ TTL 兜底。目录缺失/扫描失败 →
    None（直通不缓存）。

    aurora_f W1-S4：root 可选参数——兄弟模块（surrogate_playground）缓存
    复用同一指纹语义但扫自己的 RUNS_DIR（缺省 None=ui_service.RUNS_DIR，
    五端点行为不变）。
    """
    root = Path(root) if root is not None else Path(RUNS_DIR)
    try:
        top_sig = root.stat().st_mtime_ns
        with os.scandir(root) as it:
            dirs: list[tuple[str, int]] = []
            files: list[str] = []
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    dirs.append((e.name, e.stat(follow_symlinks=False)
                                 .st_mtime_ns))
                else:
                    files.append(e.name)
    except OSError:
        return None
    # R8-ENG2：registry 库的 sqlite 伴随文件（-wal/-shm/-journal）是连接
    # 生命周期伪条目（最后一次连接干净关闭即消失、下次连接再出现）——
    # 不属 run 数据，入指纹会让每个 UI 进程首个 sqlite 连接触发一次
    # 全端点无谓重建（实测 86ms 级）；main 库文件本体仍入指纹。
    files = [n for n in files if not n.startswith(_REG_SQLITE_SIDECAR_PREFIX)]
    dirs.sort()
    files.sort()
    return (top_sig, tuple(dirs), tuple(files))


def _cached_run_entries() -> list[tuple[Path, bool]]:
    """runs/ 顶层条目 [(Path, is_dir)] 升序（同 sorted(RUNS_DIR.iterdir())）。

    目录缺失→[]。指纹键控：任一 run 目录 mtime 变化即失效（略过失效=
    宁多扫，清单重扫仅 ~2ms）。
    """

    def _produce() -> list[tuple[Path, bool]]:
        root = Path(RUNS_DIR)
        try:
            with os.scandir(root) as it:
                out = [(root / e.name, e.is_dir()) for e in it]
        except OSError:
            return []
        return sorted(out, key=lambda t: t[0])

    return _DIR_LISTING_CACHE.get(
        (_runs_dir_key(),), _runs_fingerprint(), _produce)


def _cached_json(path: Path) -> Any:
    """(mtime_ns, size) 键控 JSON 读；缺失/解析失败→None（同既有 try/except 语义）。"""

    def _produce() -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    return _JSON_FILE_CACHE.get(
        (os.path.normcase(str(path)),), _file_signature(path), _produce)


def _cached_meta(path: Path) -> dict[str, Any]:
    """meta.json 读缓存并收敛为 dict（非 dict 值视同缺失，同既有 suppress 语义）。"""
    m = _cached_json(path)
    return m if isinstance(m, dict) else {}


def _endpoint_snapshot(name: str, produce: Any) -> Any:
    """端点级全量快照（limit 切片/排序前），指纹键控+TTL 兜底。

    签名=（runs/ 指纹, registry 索引代际）——registry 缺行降级↔covered
    升级、或回填落库改变行集时，代际递增使五端点快照即刻重建，不残留
    旧来源的 payload。返回 deepcopy——调用方（pareto/field 的 sort/slice、
    测试断言）可自由变换而不污染缓存。
    """
    value = _SNAPSHOT_CACHE.get((_runs_dir_key(), name),
                                (_runs_fingerprint(), _REG_GEN["n"]), produce)
    return copy.deepcopy(value)


def _cached_trials_count(trials_dir: Path) -> int:
    """trials/*.json 计数（目录 mtime 键控：trial 新增/删除改目录 mtime 即刻失效；
    计数只依赖文件集合，就地改写不影响正确性）。"""
    try:
        sig: int | None = trials_dir.stat().st_mtime_ns
    except OSError:
        return 0

    def _produce() -> int:
        return sum(1 for _ in trials_dir.glob("*.json"))

    return int(_RUN_SCAN_CACHE.get(
        (os.path.normcase(str(trials_dir)), "n_trials"), sig, _produce))


# ─── registry 单源索引层（R8-ENG2；五端点 model/adapter 接线）───────────────
#
# _registry_run_index()：registry 行（registry_runs_query 只读单入口）+
# （registry mtime+size, 顶层目录名集）指纹键控的索引快照。covered 态下
# calibration_runs/list_reports/pareto_runs 的条目 model/adapter 从索引取
# （零 meta.json 读）；缺行态整体回退全扫（A2-D 路径，字节等价）并后台
# 自愈回填。详见本文件头部"registry.sqlite 接线"注记。

#: registry 接线直通开关（env RFAUTO_UI_REGISTRY=0|false|off|no → 恒全扫；
#: 取值口径与 RFAUTO_UI_CACHE 一致）
_UI_REGISTRY_OFF_VALUES = _UI_CACHE_OFF_VALUES

#: registry 索引代际：索引行集/covered 态变化时 +1，进端点快照签名
_REG_GEN = {"n": 0}
_REG_GEN_LAST_SHAPE: list[Any] = [None]

#: 自愈回填批次注记（写 meta 列 backfill_batch；与 scripts/registry_backfill
#: 的 _BACKFILL_BATCH 区分来源，行语义同口径）
_REG_HEAL_BATCH = "r8_ui_selfheal"

#: run 点目录命名（api/pipeline 发射惯例；与 registry_backfill 同款）
_REG_RUN_POINT_NAME_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")

#: registry 库 sqlite 伴随文件前缀（-wal/-shm/-journal；指纹排除，见
#: _runs_fingerprint 注记）
_REG_SQLITE_SIDECAR_PREFIX = "registry.sqlite-"

#: B 类真跑证据常量（与 registry_backfill 同口径副本）
_REG_HEAL_ENGINE_DIRS = ("ads", "hfss", "openems", "comsol", "elmer")
_REG_HEAL_EVIDENCE_FILES = ("recipe.snapshot.yaml",)
_REG_HEAL_EVIDENCE_CONTENT_DIRS = ("results", "checkpoints", "trials")

#: 自愈回填节流（秒）+运行态旗标（#105 best-effort：后台单飞、失败只记日志）
_REG_HEAL_MIN_INTERVAL_S = 120.0
_REG_HEAL_STATE = {"last": 0.0, "running": False}


def _ui_registry_enabled() -> bool:
    """env RFAUTO_UI_REGISTRY=0|false|off|no → registry 零查询恒全扫。"""
    raw = os.environ.get("RFAUTO_UI_REGISTRY", "")
    return raw.strip().lower() not in _UI_REGISTRY_OFF_VALUES


def _registry_file_signature() -> tuple[int, int]:
    """registry 库文件 (mtime_ns, size)；缺席/不可 stat → (0, 0) 哨兵
    （仍落缓存——库缺席态每请求重查 sqlite 白费；自愈建库后签名变化即重建）。"""
    try:
        from rfauto.infra.db import default_registry_db_path

        st = default_registry_db_path().stat()
    except OSError:
        return (0, 0)
    return (st.st_mtime_ns, st.st_size)


def _top_dir_names() -> tuple[str, ...]:
    """runs/ 顶层目录名集（指纹的"目录数"分量；名集比纯计数多抓改名）。"""
    root = Path(RUNS_DIR)
    try:
        with os.scandir(root) as it:
            return tuple(sorted(e.name for e in it
                                if e.is_dir(follow_symlinks=False)))
    except OSError:
        return ()


def _registry_run_index() -> dict[str, Any]:
    """registry 单源索引快照（指纹键控+TTL 兜底）。

    返回 ``{"covered": bool, "rows": {run_id: (model, adapter)}}``：
    covered=True 表示 registry 覆盖盘面全部判真 run 点，rows 参与端点
    服务；covered=False 表示 registry 关闭/缺席/缺行，调用方整体回退
    全扫路径（缺行时已节流触发后台自愈回填）。
    """
    if not _ui_registry_enabled():
        return {"covered": False, "rows": {}}
    signature = (_registry_file_signature(), _top_dir_names())
    return _REG_INDEX_CACHE.get(("reg_index",), signature,
                                _produce_registry_index)


def _registry_meta_lookup() -> dict[str, tuple[str, str]] | None:
    """covered 态的 (model, adapter) 查询表；legacy/关闭 → None（回退全扫）。"""
    idx = _registry_run_index()
    return idx["rows"] if idx.get("covered") else None


def _run_meta_pair(lookup: dict[str, tuple[str, str]] | None,
                   run: Path) -> tuple[Any, Any]:
    """端点条目的 (model, adapter)：registry 行优先，豁免类/关闭回退文件读。"""
    if lookup is not None:
        got = lookup.get(run.name)
        if got is not None:
            return got
    m = _cached_meta(run / "meta.json")
    return m.get("model"), m.get("adapter")


def _produce_registry_index() -> dict[str, Any]:
    """索引生产：registry 全行 → 顶层可映射行集 + 盘面覆盖 walk（缺行检测）。

    保真过滤：run_id 含路径分隔符/点线前缀/非顶层目录（已删除、二层 run）
    不入行集；model/adapter 任一为空的行不入服务行集（B 类 no_meta_run
    行 adapter 恒空——其文件面语义 model=None，走文件读逐位一致）。
    """
    from rfauto.service.db_service import _MAX_QUERY_LIMIT, registry_runs_query

    q = registry_runs_query(limit=_MAX_QUERY_LIMIT)
    usable = bool(q.get("ok")) and bool(q.get("exists"))
    rows_all: set[str] = set()
    rows: dict[str, tuple[str, str]] = {}
    if usable:
        root = Path(RUNS_DIR)
        for r in q.get("runs") or []:
            rid = str(r.get("run_id") or "")
            if (not rid or rid in rows_all
                    or "/" in rid or "\\" in rid
                    or rid.startswith((".", "_"))):
                continue
            if not (root / rid).is_dir():
                continue  # 已删除/二层 run：顶层端点本就不展示
            rows_all.add(rid)
            model, adapter = r.get("model") or "", r.get("adapter") or ""
            if model and adapter:
                rows[rid] = (model, adapter)
    missing = _missing_registry_rows(rows_all if usable else set())
    covered = bool(usable) and not missing
    idx = {"covered": covered, "rows": rows}
    if missing:
        # 缺行（含库缺席冷启动）：节流后台自愈；db 路径先解析（线程内
        # cwd 可能已被其他请求/测试改走，#230 cwd 漂移面）。
        from rfauto.infra.db import default_registry_db_path

        _maybe_spawn_heal(missing, default_registry_db_path())
    _bump_reg_gen(idx)
    return idx


def _bump_reg_gen(idx: dict[str, Any]) -> None:
    """行集/covered 态实际变化才递增代际（TTL 到期重推导同值不重建端点快照）。"""
    shape = (bool(idx.get("covered")),
             tuple(sorted(idx.get("rows", {}).items())))
    if shape != _REG_GEN_LAST_SHAPE[0]:
        _REG_GEN_LAST_SHAPE[0] = shape
        _REG_GEN["n"] += 1


def _missing_registry_rows(rows_all: set[str]) -> list[dict[str, Any]]:
    """盘面 vs registry 覆盖差 walk（仅索引重建时跑；豁免类不计缺行）。

    缺行=A 类（判真 meta 在、库无行）与 B 类（run 点命名+真跑证据、无
    meta、库无行）；判伪/损坏 meta、helper/点线目录、零证据目录与
    registry_backfill 豁免口径一致，不入缺行。
    """
    out: list[dict[str, Any]] = []
    for d, is_dir in _cached_run_entries():
        if not is_dir:
            continue
        name = d.name
        if name in rows_all or name.startswith((".", "_")):
            continue
        meta_p = d / "meta.json"
        if meta_p.is_file():
            row = _heal_row_from_meta(meta_p)
            if row is not None:
                out.append(row)
        elif _REG_RUN_POINT_NAME_RE.match(name):
            ev = _reg_no_meta_evidence(d)
            if ev:
                out.append(_heal_row_no_meta(d, ev))
    return out


def _reg_iso(ts: float) -> str:
    """registry timestamp 列口径（与 registry_backfill._iso 同款 UTC 秒精度）。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(
        timespec="seconds")


def _heal_row_from_meta(meta_path: Path) -> dict[str, Any] | None:
    """A 类行：判真 meta.json → runs 表行（registry_backfill._row_for 同语义
    副本；判伪/损坏返回 None=豁免非缺行）。行语义与门工具逐字段一致，保证
    自愈后 scripts/registry_backfill.py --check 收敛 would_insert=0。"""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    if "adapter" not in meta and "study" not in meta:
        return None  # #144：判真=adapter/study 字段在
    run_id = meta.get("run_id") or meta_path.parent.name
    status = meta.get("status") or ("done" if meta.get("done") else "unknown")
    if isinstance(status, bool):
        status = "done" if status else "failed"
    ts_src = "dir_mtime"
    try:
        ts: float = meta_path.parent.stat().st_mtime
    except OSError:
        ts = 0.0
    for key in ("time", "timestamp", "started"):
        if meta.get(key):
            try:
                ts = datetime.fromisoformat(
                    str(meta[key]).replace("Z", "+00:00")).timestamp()
                ts_src = f"meta.{key}"
                break
            except ValueError:
                continue
    metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
    prov = {k: meta[k] for k in ("model", "adapter", "study", "seed",
                                 "recipe_version") if k in meta}
    return {
        "run_id": str(run_id),
        "model": str(meta.get("model") or meta.get("template") or ""),
        "adapter": str(meta.get("adapter") or ""),
        "status": str(status),
        "git_sha": str(meta.get("git_sha") or meta.get("git_sha_short") or ""),
        "timestamp": _reg_iso(ts),
        "metrics": json.dumps(metrics, ensure_ascii=False)[:2000],
        "meta": json.dumps(
            {**prov, "backfill_ts_source": ts_src,
             "backfill_batch": _REG_HEAL_BATCH},
            ensure_ascii=False)[:2000],
    }


def _reg_no_meta_evidence(d: Path) -> list[str]:
    """B 类真跑证据清单（registry_backfill._no_meta_evidence 同语义副本）。"""
    try:
        list(d.iterdir())  # 可读性探针（不可读目录如实按无证据处理）
    except OSError:
        return []
    ev: list[str] = []
    for name in _REG_HEAL_ENGINE_DIRS:
        if (d / name).is_dir():
            ev.append(f"dir:{name}")
    for name in _REG_HEAL_EVIDENCE_FILES:
        if (d / name).is_file():
            ev.append(f"file:{name}")
    for name in _REG_HEAL_EVIDENCE_CONTENT_DIRS:
        p = d / name
        if p.is_dir():
            try:
                if any(p.iterdir()):
                    ev.append(f"content:{name}")
            except OSError:
                pass
    return ev


def _reg_model_from_recipe_snapshot(d: Path) -> str:
    """recipe.snapshot.yaml 顶层 model: 行直读（registry_backfill 同语义副本；
    无 yaml 依赖，读不到恒空）。"""
    try:
        for line in (d / "recipe.snapshot.yaml").read_text(
                encoding="utf-8").splitlines():
            mt = re.match(r"^model:\s*(.+?)\s*$", line)
            if mt:
                return mt.group(1).split(" #", 1)[0].strip().strip("'\"")
    except OSError:
        pass
    return ""


def _heal_row_no_meta(d: Path, evidence: list[str]) -> dict[str, Any]:
    """B 类行：无 meta 真跑目录 → status/adapter 不猜（backfill 同语义副本）。"""
    try:
        ts = d.stat().st_mtime
    except OSError:
        ts = 0.0
    return {
        "run_id": d.name,
        "model": _reg_model_from_recipe_snapshot(d),
        "adapter": "",  # 无 meta 不猜
        "status": "unknown",
        "git_sha": "",
        "timestamp": _reg_iso(ts),
        "metrics": "{}",
        "meta": json.dumps(
            {"no_meta_run": True, "backfill_evidence": evidence,
             "backfill_ts_source": "dir_mtime_no_meta",
             "backfill_batch": _REG_HEAL_BATCH},
            ensure_ascii=False)[:2000],
    }


def _maybe_spawn_heal(rows: list[dict[str, Any]], db_path: Path) -> None:
    """缺行自愈回填发射（后台 daemon 线程；节流+单飞；#105 永不阻塞不抛）。"""
    now = time.monotonic()
    if now - _REG_HEAL_STATE["last"] < _REG_HEAL_MIN_INTERVAL_S:
        return
    if _REG_HEAL_STATE["running"]:
        return
    _REG_HEAL_STATE["last"] = now
    _REG_HEAL_STATE["running"] = True

    def _work() -> None:
        try:
            inserted = _self_heal_backfill(rows, db_path=db_path)
            _LOG.info("registry 自愈回填完成 db=%s missing=%d inserted=%d",
                      db_path, len(rows), inserted)
        except Exception:
            _LOG.warning("registry 自愈回填失败（best-effort，下次缺行窗口重试）",
                         exc_info=True)
        finally:
            _REG_HEAL_STATE["running"] = False

    threading.Thread(target=_work, daemon=True,
                     name="rfauto-ui-registry-heal").start()


def _self_heal_backfill(rows: list[dict[str, Any]],
                        db_path: Path | None = None) -> int:
    """缺行 INSERT OR IGNORE 进 registry（与 registry_backfill 写入口径同款；
    幂等——已存在 run_id 零改写）。返回实插行数；异常抛给发射方记日志。

    库文件缺席场景先 migrate 自举建表（backfill 假定库已存在；UI 自愈含
    冷启动建库）。全湖口径补齐（判伪/豁免分类统计等）仍以
    scripts/registry_backfill.py 为权威工具，本函数只收口 UI 读面暴露的
    缺行集合。
    """
    if not rows:
        return 0
    from rfauto.infra.db import RegistryDB, default_registry_db_path

    db = RegistryDB(
        path=db_path if db_path is not None else default_registry_db_path())
    try:
        db.migrate()
        con = db.connect()
        cur = con.executemany(
            "INSERT OR IGNORE INTO runs (run_id, model, adapter, status,"
            " git_sha, timestamp, metrics, meta) VALUES "
            "(:run_id,:model,:adapter,:status,:git_sha,:timestamp,"
            ":metrics,:meta)", rows)
        con.commit()
        return int(cur.rowcount or 0)
    finally:
        db.close()
