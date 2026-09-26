"""DP-3 锚注册表装载层：YAML 装载 + schema/provenance 校验 + mtime 缓存。

分层：core/anchors.py 纯求值内核（零 IO）← 本模块（唯一 IO 面）←
service/anchors_service.py（JSON 薄面）。装载失败 best-effort 回退空集 +
warning（#105：观测性/知识面永不阻塞业务主路径）；单锚结构坏不拖垮整表
（错误留痕进 AnchorSet.load_errors，validate 时如实上报）。

注册表运行时只读（knowledge/anchors.yaml 头注口径）：本模块无任何写路径；
漂移 stale 只翻内存面，落盘回填走人工 commit。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from rfauto.core import anchors as _core_anchors
from rfauto.core.anchors import (
    ANCHOR_KINDS,
    ANCHOR_STATUSES,
    EXPECTED_ANCHORS,
    AnchorRecord,
    AnchorSet,
)

logger = logging.getLogger(__name__)

# 默认注册表路径（源码布局；与 diagnosis.rules.yaml 同口径，wheel 安装不支持）
_DEFAULT_ANCHORS_PATH = (Path(__file__).parent.parent.parent.parent
                         / "knowledge" / "anchors.yaml")

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")

# mtime 缓存：{(normcase abs path): (st_mtime_ns, st_size, AnchorSet)}
_CACHE: dict[tuple[str, int, int], AnchorSet] = {}


def default_anchors_path() -> Path:
    """注册表默认路径（测试/服务可显式覆盖）。"""
    return _DEFAULT_ANCHORS_PATH


def load_anchors(path: str | Path | None = None,
                 *, force_reload: bool = False) -> AnchorSet:
    """装载锚注册表（mtime 缓存；失败 best-effort 空集 + warning，#105）。"""
    p = Path(path) if path else _DEFAULT_ANCHORS_PATH
    try:
        st = p.stat()
        key = (str(p.absolute()).lower(), st.st_mtime_ns, st.st_size)
    except OSError as exc:
        logger.warning("锚注册表不可读（best-effort 空集 #105）: %s (%s)", p,
                       exc)
        return AnchorSet([])
    if not force_reload:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("anchors.yaml 顶层必须是映射（schema: anchors/v1）")
        anchor_set = AnchorSet(data.get("anchors") or [])
    except Exception as exc:  # best-effort：空集不阻塞
        logger.warning("锚注册表装载失败（best-effort 空集 #105）: %s (%s)", p,
                       exc)
        return AnchorSet([])
    _CACHE[key] = anchor_set
    return anchor_set


# ── schema + provenance 校验（validate 门与 provenance 单测共用）──────────

def _resolve_repo_path(repo_root: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else repo_root / p


def validate_anchor_set(anchor_set: AnchorSet,
                        repo_root: str | Path | None = None,
                        registry_path: str | Path | None = None
                        ) -> dict[str, Any]:
    """schema + provenance 校验。返回
    ``{ok, count, issues, registry_path, expected_count, expected_match,
    load_errors}``。

    - schema：anchor_id 格式/kind/status 枚举/active 锚 uncertainty 必填/
      曲线锚 interp 口径（core 构造期校验之外的字段级核对）；
    - provenance（规格书判据 3）：arbitration_runs 路径存在（awaiting_data
      允许空）、commit 7-40 位 hex、registered_at 可解析、consumers 文件
      存在、referee_script/data_source/candidates 若给出则文件存在。
    """
    root = Path(repo_root) if repo_root else _default_repo_root()
    issues: list[str] = []

    reg_rel: str | None = None
    if registry_path is not None:
        try:
            reg_rel = str(Path(registry_path).relative_to(root))
        except ValueError:
            reg_rel = str(registry_path)

    seen: set[str] = set()
    for rec in anchor_set.records:
        _validate_record(rec, root, issues)
        seen.add(rec.anchor_id)
    issues.extend(f"load_error: {e}" for e in anchor_set.load_errors)

    expected_match = seen == set(EXPECTED_ANCHORS)
    if not expected_match:
        issues.append(
            f"锚集合与单源 EXPECTED_ANCHORS 不一致：缺失"
            f" {sorted(set(EXPECTED_ANCHORS) - seen)}，多余"
            f" {sorted(seen - set(EXPECTED_ANCHORS))}"
            "（core/anchors.py 单源需同步）")

    return {
        "ok": not issues,
        "count": len(anchor_set),
        "issues": issues,
        "registry_path": reg_rel,
        "expected_count": len(EXPECTED_ANCHORS),
        "expected_match": expected_match,
        "load_errors": list(anchor_set.load_errors),
    }


def _default_repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


def _validate_record(rec: AnchorRecord, root: Path,
                     issues: list[str]) -> None:
    aid = rec.anchor_id
    prov = rec.provenance or {}

    if rec.kind not in ANCHOR_KINDS:  # 构造期已拦，双检防旁路构造
        issues.append(f"{aid}: 未知 kind {rec.kind!r}")
    if rec.status not in ANCHOR_STATUSES:
        issues.append(f"{aid}: 未知 status {rec.status!r}")
    if rec.status == "active" and (
            not rec.uncertainty or rec.uncertainty.get("value") is None):
        issues.append(f"{aid}: active 锚 uncertainty 必填（规格书风险栏）")
    if (rec.kind == "curve" and rec.status != "awaiting_data"
            and (not rec.points or not rec.interp)):
        issues.append(f"{aid}: 非 awaiting_data 曲线锚缺 points/interp")

    # provenance：runs 路径存在（awaiting_data 允许空清单）
    runs = prov.get("arbitration_runs") or []
    if not runs and rec.status != "awaiting_data":
        issues.append(f"{aid}: provenance.arbitration_runs 为空且非 awaiting_data")
    for rel in runs:
        if not _resolve_repo_path(root, str(rel)).exists():
            issues.append(f"{aid}: arbitration_runs 路径不存在: {rel}")
    for key in ("referee_script", "data_source"):
        val = prov.get(key)
        if val and not _resolve_repo_path(root, str(val)).exists():
            issues.append(f"{aid}: provenance.{key} 文件不存在: {val}")
    for rel in prov.get("candidates") or []:
        if not _resolve_repo_path(root, str(rel)).exists():
            issues.append(f"{aid}: provenance.candidates 路径不存在: {rel}")

    commit = prov.get("commit")
    if commit:
        if not _COMMIT_RE.match(str(commit).lower()):
            issues.append(f"{aid}: provenance.commit 不可解析: {commit!r}")
    elif rec.status != "awaiting_data":
        issues.append(f"{aid}: provenance.commit 缺失")

    if rec.registered_at:
        try:
            datetime.fromisoformat(str(rec.registered_at))
        except ValueError:
            issues.append(
                f"{aid}: registered_at 不可解析: {rec.registered_at!r}")
    else:
        issues.append(f"{aid}: registered_at 缺失")

    for rel in rec.consumers:
        if not _resolve_repo_path(root, str(rel)).exists():
            issues.append(f"{aid}: consumers 文件不存在: {rel}")

    lv = rec.last_verified
    if lv is not None:
        try:
            datetime.fromisoformat(str(lv.get("at")))
        except (ValueError, AttributeError):
            issues.append(f"{aid}: last_verified.at 不可解析: {lv!r}")


# ── 消费接线（DP-3 第二批，df7 锚消费第二批）───────────────────────────────
# core 零 IO 不 import 本模块——活注册表经 core/anchors 的接插点反向注册
# （infra→core 合法方向）：本模块被导入即激活锚消费路径（core/calculators
# 的 cps.gamma_er/siw.w_eff 公式锚消费自此可解析）。未导入本模块的进程
# （纯 core 使用面）消费者走字面/闭式回退——值逐位同（#105 best-effort）。
_core_anchors.set_live_anchor_set_provider(load_anchors)
