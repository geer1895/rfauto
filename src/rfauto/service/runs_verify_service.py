"""runs_verify_service：run 级产物新鲜度指纹（K4，aurora_k 战役，P11/F7）。

用户实测病灶：交付图引用的 ``results_final/wp/ind_wp.s1p`` 文件头是 13:05
的旧工程，而修好后的运行是 19:29；19:45 拷回工作区时该文件漏拷——同一目录
同一文件名同一条绘图脚本，没有任何机制能发现错配，最终交付了错误结论
（"无盖板电感 L≈0.135 nH"）。这不是数值误差，是**结果新鲜度**问题。

本模块给 run 目录落两层指纹，出报告前先校验：

- ``manifest.json``（run 级）：run 收官时聚合 recipe 快照哈希 + 全部
  Touchstone 文件清单（sha256/size/mtime）+ 声明式产物指纹（K20 审查③：
  ``results/metrics.json``、``results/report.md``——存在才记，不存在不记
  不报；报告主数据源被顶替也必须红）+ meta.json 关键字段的**引用**
  （aedt_version/git_sha 等 meta 已有的直接引用，不重算）；
- ``<name>.sNp.meta.json``（sidecar，Touchstone 落盘点旁）：run_id + sha256
  + 设计名 + Setup/Sweep + 导出时间——文件级自描述，脱离 run 目录拷到
  交付目录后仍可查（HFSS 导出头自带 File/Generated/Design 注释，但引擎
  自算的 mtime/哈希与 run 归属仍需 sidecar 补全）。

B4（aurora_l Wave-B）泛化：``write_artifact_sidecar`` 把 sidecar 从
Touchstone 专用推广到全部适配器的曲线产物（``sparams.csv``/``.s2p`` 形态，
openEMS 主 chokepoint+rotation+comsol/ngsolve/mmt/pssfss/qucsator 各解析
落盘点接线）；manifest 相应增 ``curves_csv`` 段（存在才记，同款 sha 比对
+sidecar 交叉核对；老 manifest 缺段跳过，双向增量兼容）。

``verify_run`` 三态（+untracked 分级）：

- ``fresh``：manifest 记录的每个文件（Touchstone+声明式产物+recipe 快照）
  盘上 sha256 逐一相符；
- ``stale``：任一记录文件 sha 不符（``stale_replaced``——**用户验收场景：
  旧 s1p 放进新 run 目录必须红**；recipe 快照被顶替=``snapshot_replaced``，
  K20 审查②：manifest 记了快照哈希却从不回查，旧快照可冒充 fresh，已修）
  /记录文件消失（``missing``——漏拷形态；recipe 快照丢失=``snapshot_missing``
  ——快照是 recipe 证据，丢=不可信）/文件存在但读不出来（``unreadable``
  ——Windows 文件锁等 OSError 形态；读不出来即按不可信处理不静默放行，
  K20 审查 P1：原实现记 issue 却不入 stale 级，自述与行为相反，已修）
  /sidecar 哈希与盘上内容不符（``sidecar_mismatch``）/manifest 本身损坏
  （``manifest_corrupt``——无法作证即不作证，多报不放过 #316）；
- ``legacy``：run 无 manifest（老 run/未接线链路）——如实声明不伪造，
  消费方（report 门）放行带 note（增量兼容红线：老 run 行为不变）；
  manifest 缺 ``recipe_snapshot``/``artifacts`` 段（老 manifest 只指纹过
  Touchstone）按段在场与否分派，缺段跳过——双向增量兼容；
- ``untracked_new``：盘上出现 manifest 未登记的 Touchstone（mtime 晚于
  manifest 生成时刻）——如实分级为 issue 但**不算 stale**（新增产物不是
  错配；典型=事后补拷的附加曲线）。

实现约束：观测面 best-effort（#105）——落盘接线（run_core 收尾钩子）失败
只记 warning 不阻塞求解/报告主路径；``verify_run`` 本身只读不写。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

logger = logging.getLogger(__name__)

#: 指纹清单 schema 版本（形状变更时升位）。
RUNS_VERIFY_SCHEMA_VERSION = 1

#: run 级指纹文件名（落 run 目录根，与 meta.json 同级）。
MANIFEST_FILENAME = "manifest.json"

#: Touchstone 扩展名模式（.s1p/.s2p/…/.s32p，大小写不敏感）。
_TOUCHSTONE_RE = re.compile(r"\.s\d+p$", re.IGNORECASE)

#: 曲线 CSV 文件名模式（B4，aurora_l Wave-B）：``sparams.csv`` 及前缀变体
#: （qucsator_sparams.csv），大小写不敏感。
_CURVES_CSV_RE = re.compile(r"(?:^|_)sparams\.csv$", re.IGNORECASE)

#: 声明式产物指纹清单（K20 审查③：报告主数据源 metrics.json 被顶替也必须
#: 红）——存在才记，不存在不记不报；verify 侧按 ``artifacts`` 段在场与否
#: 分派，老 manifest（只指纹过 Touchstone）缺段跳过，双向增量兼容。
_DECLARATIVE_ARTIFACTS: tuple[str, ...] = (
    "results/metrics.json",
    "results/report.md",
)

#: manifest 引用的 meta.json 字段（已有值直接引用不重算；缺失键不落）。
_META_REF_KEYS: tuple[str, ...] = (
    "run_id", "adapter", "model", "status", "study_name",
    "aedt_version", "ads_version", "git_sha", "package_version",
    "plugin_version", "timestamp", "solver_versions", "seed",
)

#: stale 级 issue 种类（任一命中 → status=stale，report 拒绝出图）。
#:
#: ``unreadable`` 入级（K20 审查 P1）：读不出来即按不可信处理——原实现
#: 记 issue 却不入本集合，行内注释"不静默放行"与实际 fresh 放行相反；
#: ``snapshot_replaced``/``snapshot_missing`` 为 recipe 快照回查专用种类。
_STALE_KINDS = frozenset({
    "stale_replaced", "missing", "unreadable", "sidecar_mismatch",
    "manifest_corrupt", "snapshot_replaced", "snapshot_missing",
})


def _sha256_file(path: Path) -> str:
    """文件内容 sha256（裸十六进制）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fid:
        for chunk in iter(lambda: fid.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    """单文件指纹：内容 sha256 + size + mtime（epoch 秒）。"""
    stat = path.stat()
    return {
        "sha256": _sha256_file(path),
        "size": int(stat.st_size),
        "mtime": float(stat.st_mtime),
    }


def _iter_touchstones(run_dir: Path) -> list[tuple[str, Path]]:
    """run 目录内全部 Touchstone 文件，按相对 POSIX 路径排序（确定性）。"""
    pairs = [
        (p.relative_to(run_dir).as_posix(), p)
        for p in run_dir.rglob("*")
        if p.is_file() and _TOUCHSTONE_RE.search(p.name)
    ]
    pairs.sort(key=lambda item: item[0])
    return pairs


def _iter_curves_csv(run_dir: Path) -> list[tuple[str, Path]]:
    """run 目录内全部曲线 CSV（sparams.csv 形态），按相对 POSIX 路径排序。"""
    pairs = [
        (p.relative_to(run_dir).as_posix(), p)
        for p in run_dir.rglob("*")
        if p.is_file() and _CURVES_CSV_RE.search(p.name)
    ]
    pairs.sort(key=lambda item: item[0])
    return pairs


def _load_meta(run_dir: Path) -> dict[str, Any] | None:
    """读 run 目录 meta.json（best-effort：缺失/损坏返回 None）。"""
    meta_path = run_dir / "meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_run_dir(run_ref: str | Path) -> Path:
    """CLI 入参归一：显式目录优先，回退 ``runs/<run_ref>``（双根收敛）。

    分层：cli 不得直 import infra（import-linter 契约），runs/ 面路径单源
    （infra.runs_paths）经本 service 出口转接——health_service 同款语义。
    回退也不在场时原样返回显式路径（verify_run 对不存在目录走干净错误）。
    """
    candidate = Path(run_ref)
    if candidate.is_dir():
        return candidate
    from rfauto.infra.runs_paths import resolve_runs_dir

    alt = resolve_runs_dir(Path("runs") / str(run_ref))
    return alt if alt.is_dir() else candidate


def manifest_for_run(run_dir: str | Path) -> dict[str, Any]:
    """聚合 run 当前盘面状态的指纹清单（纯计算，不写盘）。

    指纹面：meta.json 关键字段引用（直接引用不重算）+ recipe 快照哈希 +
    全部 Touchstone 的 sha256/size/mtime 清单 + 声明式产物（``artifacts``
    段，存在才记）+ 生成时刻。老 run 同样可算（按当前盘面如实聚合）——
    但**是否新鲜**由 :func:`verify_run` 对照 manifest.json 落盘记录判定；
    无落盘记录的 run 判 legacy，不伪造。

    Raises:
        ValueError: run_dir 不是存在的目录（#140：入参显式报错，不静默）。
    """
    run_path = Path(run_dir)
    if not run_path.is_dir():
        raise ValueError(f"run 目录不存在或非目录: {run_path}")

    meta = _load_meta(run_path) or {}
    meta_ref = {key: meta[key] for key in _META_REF_KEYS if key in meta}

    touchstones: dict[str, dict[str, Any]] = {}
    for rel, path in _iter_touchstones(run_path):
        try:
            touchstones[rel] = _file_fingerprint(path)
        except OSError as exc:
            logger.warning("manifest 指纹采集失败（跳过 %s）: %s", rel, exc)

    # 曲线 CSV 指纹段（B4，aurora_l Wave-B：存在才记，采集失败 best-effort
    # 跳过 #105；老 run 无 CSV 同样可算，verify 侧缺段跳过双向兼容）
    curves_csv: dict[str, dict[str, Any]] = {}
    for rel, path in _iter_curves_csv(run_path):
        try:
            curves_csv[rel] = _file_fingerprint(path)
        except OSError as exc:
            logger.warning("曲线 CSV 指纹采集失败（跳过 %s）: %s", rel, exc)

    # 声明式产物（存在才记，不存在不记不报；采集失败 best-effort 跳过 #105）
    artifacts: dict[str, dict[str, Any]] = {}
    for rel in _DECLARATIVE_ARTIFACTS:
        artifact_path = run_path / rel
        if not artifact_path.is_file():
            continue
        try:
            artifacts[rel] = _file_fingerprint(artifact_path)
        except OSError as exc:
            logger.warning("声明式产物指纹采集失败（跳过 %s）: %s", rel, exc)

    recipe: dict[str, Any] | None = None
    recipe_path = run_path / "recipe.snapshot.yaml"
    if recipe_path.is_file():
        try:
            recipe = {"path": recipe_path.name,
                      "sha256": _sha256_file(recipe_path),
                      "size": int(recipe_path.stat().st_size)}
        except OSError as exc:
            logger.warning("recipe 快照指纹失败（非阻断）: %s", exc)

    return {
        "schema_version": RUNS_VERIFY_SCHEMA_VERSION,
        "generator": "rfauto.service.runs_verify_service",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(meta.get("run_id") or run_path.name),
        "meta_ref": meta_ref,
        "recipe_snapshot": recipe,
        "touchstones": touchstones,
        "touchstone_count": len(touchstones),
        "curves_csv": curves_csv,
        "curves_csv_count": len(curves_csv),
        "artifacts": artifacts,
    }


def write_manifest(run_dir: str | Path) -> dict[str, Any]:
    """指纹清单落盘 ``<run_dir>/manifest.json``（run 收官钩子调用点）。

    调用方（run_core 收尾）负责 best-effort 包裹（#105：失败不阻塞求解
    产物）；本函数自身对非法入参显式 ValueError（与 manifest_for_run 同口径）。
    """
    run_path = Path(run_dir)
    manifest = manifest_for_run(run_path)
    dest = run_path / MANIFEST_FILENAME
    dest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8")
    return ok_envelope(path=str(dest), touchstone_count=manifest["touchstone_count"])


def write_artifact_sidecar(
    artifact_path: str | Path,
    *,
    run_id: str = "",
    kind: str = "sparams_csv",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """曲线产物落盘点旁写 ``<name>.meta.json`` 指纹 sidecar（B4 泛化）。

    内容统一=kind+run_id+sha256+size+mtime+导出时间（+extra 透传键）。
    文件级自描述：即使被拷出 run 目录（交付目录形态），sidecar 跟文件走，
    错配可查。best-effort 语义同上（调用方包裹）。

    Args:
        artifact_path: 已落盘的产物文件（``sparams.csv``/``.sNp`` 等）。
        run_id: 归属标识（适配器接线取各自 run/工作目录名）。
        kind: 产物类型标注（``touchstone``/``sparams_csv``，仅自描述不参与比对）。
        extra: 附加键（Touchstone 薄壳透传 design_name/setup/sweep）。
    """
    path = Path(artifact_path)
    if not path.is_file():
        raise ValueError(f"产物文件不存在，sidecar 无从落: {path}")
    sidecar: dict[str, Any] = {
        "schema_version": RUNS_VERIFY_SCHEMA_VERSION,
        "generator": "rfauto.service.runs_verify_service",
        "kind": str(kind),
        "run_id": str(run_id),
        "sha256": _sha256_file(path),
        "size": int(path.stat().st_size),
        "mtime": float(path.stat().st_mtime),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        sidecar.update(extra)
    dest = path.parent / f"{path.name}.meta.json"
    dest.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8")
    return ok_envelope(path=str(dest), kind=str(kind))


def write_touchstone_sidecar(
    touchstone_path: str | Path,
    *,
    run_id: str = "",
    design_name: str = "",
    setup: str = "",
    sweep: str = "",
) -> dict[str, Any]:
    """Touchstone 落盘点旁写 sidecar（K4 兼容薄壳=B4 泛化的 touchstone 形态）。

    内容=run_id+sha256+size+设计名+Setup/Sweep+导出时间+kind。既有调用面
    （run_core K4 钩子/测试）签名与行为不变。best-effort 语义同上（调用方
    包裹）。
    """
    return write_artifact_sidecar(
        touchstone_path, run_id=run_id, kind="touchstone",
        extra={"design_name": str(design_name), "setup": str(setup),
               "sweep": str(sweep)})


def _parse_generated_at(value: Any, fallback_epoch: float) -> float:
    """manifest 生成时刻 → epoch 秒（解析失败回退 manifest 文件 mtime）。"""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            pass
    return float(fallback_epoch)


def _load_manifest(run_dir: Path) -> dict[str, Any] | None:
    """读 manifest.json；不存在返回 None，损坏/非对象返回 {"__corrupt__": …}。"""
    path = run_dir / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"__corrupt__": f"{type(exc).__name__}: {exc}"}
    if not isinstance(data, dict):
        return {"__corrupt__": f"manifest 根节点需为 JSON 对象，实际 {type(data).__name__}"}
    return data


def _issue_for_recorded_file(
        run_path: Path, rel: str, expected: Any) -> tuple[dict[str, Any] | None,
                                                          str | None]:
    """记录文件 vs 盘上内容单一比对（Touchstone/声明式产物/recipe 快照共用）。

    返回 ``(issue, actual_sha256)``：缺失=``missing``（漏拷/被删）、读不出=
    ``unreadable``（读不出来即按不可信处理，不静默放行——K20 审查 P1：原
    实现记 issue 却不入 stale 级，自述与行为相反，已修）——均无 actual 可言，
    返回 ``(issue, None)``；sha 不符=``stale_replaced`` 返回 ``(issue, actual)``
    （actual 留给 sidecar 交叉比对）；相符返回 ``(None, actual)``。
    """
    path = run_path / rel
    if not path.is_file():
        return {"kind": "missing", "path": rel,
                "recorded_sha256": expected,
                "detail": "manifest 记录的文件不在盘上（漏拷/被删）"}, None
    try:
        actual = _sha256_file(path)
    except OSError as exc:
        return {"kind": "unreadable", "path": rel,
                "recorded_sha256": expected,
                "detail": f"文件存在但读不出来，无法作证（{exc}）"
                          "——读不出来即按不可信处理，不静默放行"}, None
    if expected and actual != expected:
        return {"kind": "stale_replaced", "path": rel,
                "recorded_sha256": expected, "actual_sha256": actual,
                "detail": "盘上内容与 manifest 记录不符（旧文件顶替/内容被改）"}, actual
    return None, actual


def _check_recorded_section(
        run_path: Path, recorded: Any,
        issues: list[dict[str, Any]]) -> None:
    """manifest 记录段统一比对（Touchstone/曲线 CSV 共用，B4 抽取）。

    逐文件：盘上 sha256 vs 记录（``stale_replaced``/``missing``/``unreadable``，
    stale 级）+ sidecar 交叉核对（``sidecar_mismatch``；sidecar 在场才查，
    缺席不虚构）。非 dict 段（老 manifest 缺 ``curves_csv`` 段等）跳过——
    双向增量兼容。
    """
    if not isinstance(recorded, dict):
        return
    for rel in sorted(recorded):
        entry = recorded[rel] if isinstance(recorded[rel], dict) else {}
        issue, actual = _issue_for_recorded_file(
            run_path, rel, entry.get("sha256"))
        if issue is not None:
            issues.append(issue)
            if issue["kind"] != "stale_replaced":
                continue  # missing/unreadable：sidecar 无从交叉比对
        path = run_path / rel
        # sidecar 交叉核对（在场才查，缺席不虚构）
        sidecar_path = path.parent / f"{path.name}.meta.json"
        if sidecar_path.is_file():
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append({"kind": "sidecar_mismatch", "path": rel,
                               "detail": f"sidecar 不可读: {exc}"})
                continue
            recorded_sc = sidecar.get("sha256") if isinstance(sidecar, dict) else None
            if recorded_sc and recorded_sc != actual:
                issues.append({
                    "kind": "sidecar_mismatch", "path": rel,
                    "sidecar_sha256": recorded_sc, "actual_sha256": actual,
                    "detail": "sidecar 记录的哈希与盘上内容不符（文件级错配证据）"})


def verify_run(run_dir: str | Path) -> dict[str, Any]:
    """run 产物新鲜度三查（只读）：盘上 sha vs manifest 记录/未登记新增/缺 manifest。

    Returns:
        信封 ``{ok, run_id, status: fresh|stale|legacy, issues: [...]}``——
        stale → ok=False（CLI 退出码 1 / report 拒绝出图）；legacy → ok=True
        放行（note 说明，老 run 不废）；fresh → ok=True（issues 可含
        untracked_new 信息级条目）。
    """
    # #140：PathLike 入参第一行收敛
    run_path = Path(run_dir)
    run_id = run_path.name
    if not run_path.is_dir():
        return error_envelope(
            f"run 目录不存在: {run_path}（传入 run 目录路径，或 runs/ 下的 "
            "run_id 目录名）",
            run_id=run_id, status="error", issues=[])

    manifest = _load_manifest(run_path)
    if manifest is None:
        return ok_envelope(
            run_id=run_id, status="legacy", legacy=True, issues=[],
            note="run 无 manifest.json（老 run/未接线链路）：无指纹可比，"
                 "新鲜度校验不适用，按 legacy 放行")
    if "__corrupt__" in manifest:
        return error_envelope(
            [f"manifest.json 损坏，无法作证新鲜度: {manifest['__corrupt__']}"
             "（重跑一次 run 可重建指纹）"],
            run_id=run_id, status="stale", issues=[
                {"kind": "manifest_corrupt", "path": MANIFEST_FILENAME,
                 "detail": str(manifest["__corrupt__"])}])

    manifest_path = run_path / MANIFEST_FILENAME
    generated_epoch = _parse_generated_at(
        manifest.get("generated_at"), manifest_path.stat().st_mtime)
    if isinstance(manifest.get("run_id"), str) and manifest["run_id"]:
        run_id = manifest["run_id"]

    recorded: dict[str, Any] = manifest.get("touchstones") or {}
    if not isinstance(recorded, dict):
        recorded = {}

    issues: list[dict[str, Any]] = []
    # ① 记录在案的 Touchstone：盘上 sha256 逐一对照（stale 级）+ sidecar 交叉核对
    _check_recorded_section(run_path, manifest.get("touchstones"), issues)
    # ①a 曲线 CSV 段（B4，aurora_l Wave-B）：sparams.csv 形态同款 sha 比对 +
    #    sidecar 交叉核对；manifest 无段（只指纹过 Touchstone 的老 manifest）
    #    跳过兼容。
    _check_recorded_section(run_path, manifest.get("curves_csv"), issues)

    # ①b recipe 快照回查（K20 审查②）：manifest 有 recipe_snapshot 段才查，
    #    老 manifest 缺段跳过（增量兼容）。快照是 recipe 证据：被旧快照顶替
    #    （snapshot_replaced）/丢失（snapshot_missing）即不可信，均为 stale 级。
    recorded_recipe = manifest.get("recipe_snapshot")
    if isinstance(recorded_recipe, dict) and recorded_recipe:
        recipe_rel = str(recorded_recipe.get("path") or "recipe.snapshot.yaml")
        issue, _ = _issue_for_recorded_file(
            run_path, recipe_rel, recorded_recipe.get("sha256"))
        if issue is not None:
            if issue["kind"] == "missing":
                issue["kind"] = "snapshot_missing"
                issue["detail"] = ("manifest 记录的 recipe 快照不在盘上"
                                   "（recipe 证据丢失即不可信）")
            elif issue["kind"] == "stale_replaced":
                issue["kind"] = "snapshot_replaced"
                issue["detail"] = ("盘上 recipe 快照与 manifest 记录不符"
                                   "（旧快照顶替/内容被改）")
            issues.append(issue)

    # ①c 声明式产物（K20 审查③：报告主数据源 metrics.json 被顶替也必须红）
    #    ——同款 sha 比对；manifest 无 ``artifacts`` 段（只指纹过 Touchstone
    #    的老 manifest）跳过兼容。
    recorded_artifacts = manifest.get("artifacts")
    if isinstance(recorded_artifacts, dict):
        for rel in sorted(recorded_artifacts):
            entry = (recorded_artifacts[rel]
                     if isinstance(recorded_artifacts[rel], dict) else {})
            issue, _ = _issue_for_recorded_file(run_path, rel, entry.get("sha256"))
            if issue is not None:
                issues.append(issue)

    # ② manifest 未登记的盘上 Touchstone：mtime 晚于 manifest 生成 →
    #    untracked_new（信息级，不算 stale）；早于/同时 → untracked（同信息级）
    for rel, path in _iter_touchstones(run_path):
        if rel in recorded:
            continue
        try:
            newer = float(path.stat().st_mtime) > generated_epoch
        except OSError:
            newer = False
        issues.append({
            "kind": "untracked_new" if newer else "untracked",
            "path": rel,
            "detail": "manifest 未登记的 Touchstone"
                      f"（{'晚于' if newer else '不晚于'} manifest 生成时刻）"
                      "——信息级，不算 stale"})

    issues.sort(key=lambda issue: (issue.get("kind", ""), issue.get("path", "")))
    is_stale = any(issue.get("kind") in _STALE_KINDS for issue in issues)
    if is_stale:
        return error_envelope(
            [f"{issue['kind']}: {issue['path']}（{issue.get('detail', '')}）"
             for issue in issues if issue.get("kind") in _STALE_KINDS],
            run_id=run_id, status="stale", issues=issues,
            note="run 产物新鲜度校验未通过：盘上产物（Touchstone/曲线 CSV/"
                 "声明式产物/recipe 快照）与 run 收尾时记录的指纹不符，拒绝"
                 "采信（交付错配风险）——确认文件来源后补拷正确文件或重跑该 "
                 "run，再复检")
    return ok_envelope(run_id=run_id, status="fresh", issues=issues,
                       note="" if not issues else "含信息级 issue（untracked），"
                       "不影响新鲜度判定")
