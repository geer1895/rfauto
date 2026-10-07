"""代理模型资产注册表内核（RB-ML-1，sa_specs2 §六）。

与 ``optimization/surrogate/base.py`` 的 ``SurrogateRegistry``（类工厂注册
表：kind → 可实例化模型类）**正交**：本件管理**训练产物资产**——版本/
血缘/champion-challenger/漂移失效四件事（MLflow Model Registry 模式参照，
非依赖引入——负结果台账已裁）。

存储形态（spec §6.2-1）：
- 元数据：``knowledge/surrogate_registry.yaml``（tracked；缺省相对 cwd，
  路径可注入）；
- 模型 blob：``runs/.model_store/<sha256>.pkl``（gitignored 内容寻址，
  dag_cache file_sha256 同法；pickle 仅消费本仓产物——spec §6.4 风险面，
  反序列化前强制 sha256 复核）；
- 键：``{template_family, channel, feature_set_fingerprint}``——指纹=
  特征名+顺序+预处理的 sha256 前 16（RB-ML-3 特征快照共键，未来件）；
  读取面按指纹**精确匹配**，不模糊复用（schema 演进=旧键自然失配）。

并发与原子性（spec §6.3-4）：
- 版本号=键内 max+1，分配在文件锁（O_EXCL 重试+陈旧锁接管）+进程内
  RLock 双层之下；
- YAML 写=临时文件+``os.replace`` 原子替换（dag_cache 同法，Windows 安全）。

best-effort 边界（#105）：本内核的调用方（service 面/surrogate_loop 收尾
钩子）负责 try 包裹——注册失败不阻塞战役；内核自身对可预期坏输入返回
``{"ok": False, "reason": ...}`` 而不抛（blob 损坏/缺失/键缺失类）。

数值纪律（铁律 7）：本件不产生物理数字——heldout 误差由确定性代理模型
（surrogate_registry 既有内核）对留出样本预测后与实测 cost 差值得出；
champion 预测点同理（service 面消费）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pickle
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "FINGERPRINT_LEN",
    "KEY_FIELDS",
    "REGISTRY_SCHEMA_VERSION",
    "STATUS_CHALLENGER",
    "STATUS_CHAMPION",
    "STATUS_RETIRED",
    "ModelRegistry",
    "canonical_key",
    "current_git_sha",
    "default_model_store_dir",
    "default_registry_path",
    "feature_set_fingerprint",
    "heldout_linf",
    "key_sort_id",
    "registry_write_enabled",
    "upsert_from_surrogate_loop",
]

REGISTRY_SCHEMA_VERSION = 1
STATUS_CHAMPION = "champion"
STATUS_CHALLENGER = "challenger"
STATUS_RETIRED = "retired"

#: 注册键字段（spec §6.2-1 schema；顺序即 canonical json 序）。
KEY_FIELDS: tuple[str, ...] = (
    "template_family", "channel", "feature_set_fingerprint")
FINGERPRINT_LEN = 16

LOCK_TIMEOUT_S = 10.0     #: 文件锁获取上限（超时抛 TimeoutError，不静默）
LOCK_STALE_S = 120.0      #: 陈旧锁接管阈值（持有者崩溃残留）
_BLOB_EXT = ".pkl"

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


def default_registry_path() -> Path:
    """注册表元数据缺省路径（相对 cwd；spec §6.2-1）。"""
    return Path("knowledge") / "surrogate_registry.yaml"


def default_model_store_dir() -> Path:
    """模型 blob 缺省落点（runs/ 已整体 gitignore）。"""
    return Path("runs") / ".model_store"


def feature_set_fingerprint(
    feature_names: list[str],
    preprocessing: dict[str, Any] | None = None,
) -> str:
    """特征集指纹：特征名+顺序+预处理 → sha256 前 16（spec §6.2-1）。

    canonical json（sort_keys）保证同内容同指纹；顺序敏感（列表序原样
    进哈希）——特征重排=新键，读取面自然失配不模糊复用。
    """
    payload = json.dumps(
        {"features": [str(n) for n in feature_names],
         "preprocessing": dict(preprocessing or {})},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:FINGERPRINT_LEN]


def canonical_key(
    template_family: str, channel: str, feature_set_fingerprint: str,
) -> dict[str, str]:
    """构造注册键（三字段全必填，空串显式拒绝——键含糊即血缘断）。"""
    key = {
        "template_family": str(template_family),
        "channel": str(channel),
        "feature_set_fingerprint": str(feature_set_fingerprint),
    }
    missing = [f for f in KEY_FIELDS if not key[f]]
    if missing:
        raise ValueError(f"注册键字段不得为空: {missing}")
    return key


def key_sort_id(key: dict[str, Any]) -> str:
    """键的 canonical json 串（entries 排序/查找单源）。"""
    return json.dumps({f: str(key.get(f) or "") for f in KEY_FIELDS},
                      sort_keys=True, ensure_ascii=False)


def utc_now_iso() -> str:
    """UTC ISO 时间戳（created_at 字段单源）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_git_sha(cwd: str | Path | None = None) -> str | None:
    """当前 git HEAD sha（best-effort #105：任何失败返回 None 不抛）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(cwd or Path.cwd()),
            capture_output=True, text=True, timeout=10, check=True,
        )
        sha = out.stdout.strip()
        return sha or None
    except Exception:  # 观测性 best-effort（#105）
        return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, buf_size: int = 1 << 20) -> str:
    """文件 sha256（blob 完整性复核单源，lake_service._sha256_file 同法）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buf_size):
            h.update(chunk)
    return h.hexdigest()


def registry_write_enabled(environ: dict[str, str] | None = None) -> bool:
    """训练写点环境门（缺省关=旧环境行为逐字节不变，spec §6.3-6）。"""
    env = os.environ if environ is None else environ
    return str(env.get("RFAUTO_SURROGATE_REGISTRY_WRITE", "")).strip().lower() \
        in _TRUE_STRINGS


# ─── 注册表存储 ───────────────────────────────────────────────────────────────


class ModelRegistry:
    """训练产物注册表（YAML 元数据 + 内容寻址 blob，路径可注入）。"""

    def __init__(
        self,
        registry_path: str | Path | None = None,
        store_dir: str | Path | None = None,
    ) -> None:
        self.registry_path = Path(
            registry_path) if registry_path else default_registry_path()
        self.store_dir = Path(
            store_dir) if store_dir else default_model_store_dir()
        self._rlock = threading.RLock()

    # ── 读写基元 ─────────────────────────────────────────────────────────────

    def load(self) -> dict[str, Any]:
        """读注册表文档；文件不存在=空注册表（spec §6.3-6 零退化）。

        文件存在但 YAML 非法/顶层结构不对 → ValueError（坏账不静默吞，
        消费面自行 try 包裹决定降级姿势）。
        """
        import yaml

        if not self.registry_path.exists():
            return {"schema_version": REGISTRY_SCHEMA_VERSION, "entries": []}
        try:
            with open(self.registry_path, encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"注册表 YAML 解析失败（坏账不静默吞）: {exc}") from exc
        if doc is None:
            return {"schema_version": REGISTRY_SCHEMA_VERSION, "entries": []}
        if not isinstance(doc, dict) or not isinstance(
                doc.get("entries"), list):
            raise ValueError(
                f"注册表文件结构非法（entries 须为列表）: {self.registry_path}")
        return doc

    def _save(self, doc: dict[str, Any]) -> None:
        """原子写（tmp + os.replace；调用方须已持锁）。"""
        import yaml

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.registry_path.with_suffix(
            self.registry_path.suffix + f".tmp{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, self.registry_path)

    def _entries(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        return doc.setdefault("entries", [])

    @staticmethod
    def _find_entry(doc: dict[str, Any], key: dict[str, Any]) -> dict | None:
        kid = key_sort_id(key)
        for entry in doc.get("entries") or []:
            if key_sort_id(entry.get("key") or {}) == kid:
                return entry
        return None

    @contextlib.contextmanager
    def _locked(self):
        """互斥上下文：进程内 RLock + 跨进程 O_EXCL 锁文件（陈旧可接管）。

        锁文件落 store_dir（gitignored），名含注册表文件名防多注册表互踩。
        """
        with self._rlock:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.store_dir / (self.registry_path.name + ".lock")
            deadline = time.monotonic() + LOCK_TIMEOUT_S
            acquired = False
            fd = None
            while True:
                try:
                    fd = os.open(
                        lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    acquired = True
                    break
                except FileExistsError:
                    try:
                        age = time.time() - lock_path.stat().st_mtime
                    except FileNotFoundError:
                        continue
                    if age > LOCK_STALE_S:
                        # 陈旧锁接管（持有者崩溃残留）；Windows 下活进程
                        # 占用期 unlink 失败→按未过期处理走超时路径
                        try:
                            lock_path.unlink()
                        except OSError:
                            pass
                        else:
                            continue
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            f"注册表锁获取超时: {lock_path}") from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                if acquired:
                    with contextlib.suppress(FileNotFoundError):
                        if fd is not None:
                            os.close(fd)
                        lock_path.unlink()

    # ── blob 面 ──────────────────────────────────────────────────────────────

    def _store_blob(self, data: bytes) -> tuple[str, str]:
        """内容寻址落 blob：返回 (sha256, 展示路径 posix 串)。"""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        sha = sha256_bytes(data)
        blob = self.store_dir / f"{sha}{_BLOB_EXT}"
        if not blob.exists():
            tmp = blob.with_suffix(blob.suffix + f".tmp{os.getpid()}")
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, blob)
        return sha, self._display_path(blob)

    @staticmethod
    def _display_path(path: Path) -> str:
        """展示路径：cwd 下给相对 posix 串，否则绝对 posix（spec 示例形态）。"""
        p = Path(path)
        try:
            return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            return p.resolve().as_posix()

    def load_entry_model(self, entry: dict[str, Any]) -> dict[str, Any]:
        """按版本条目加载模型：先 sha256 复核 blob 再反序列化（§6.3-5）。

        Returns:
            ``{"ok": True, "model": ...}`` 或
            ``{"ok": False, "reason": "blob_missing"|"blob_sha256_mismatch"|
            "unpickle_failed", "detail": ...}``——拒用不崩溃。
        """
        blob_path = entry.get("blob_path")
        expect = entry.get("model_blob_sha256")
        if not blob_path or not expect:
            return {"ok": False, "reason": "blob_missing",
                    "detail": "条目缺 blob_path/model_blob_sha256"}
        blob = Path(str(blob_path))
        if not blob.exists() and str(expect):
            # cwd 漂移兜底：blob 内容寻址可由 store_dir 重建定位
            candidate = self.store_dir / f"{expect}{_BLOB_EXT}"
            if candidate.exists():
                blob = candidate
        if not blob.exists():
            # 展示路径相对 cwd；展示与解析同源（_display_path 生成）
            return {"ok": False, "reason": "blob_missing",
                    "detail": f"blob 不存在: {blob_path}"}
        try:
            actual = sha256_file(blob)
        except OSError as exc:
            return {"ok": False, "reason": "blob_missing",
                    "detail": f"blob 不可读: {exc}"}
        if actual != str(expect):
            return {"ok": False, "reason": "blob_sha256_mismatch",
                    "detail": f"期望 {expect} 实测 {actual}"}
        try:
            with open(blob, "rb") as f:
                model = pickle.load(f)
        except Exception as exc:
            return {"ok": False, "reason": "unpickle_failed",
                    "detail": f"{exc}"}
        return {"ok": True, "model": model}

    # ── 查询面 ───────────────────────────────────────────────────────────────

    def query(
        self,
        *,
        template_family: str | None = None,
        channel: str | None = None,
        status: str | None = None,
        stale: bool | None = None,
    ) -> list[dict[str, Any]]:
        """展平版本行（键字段+版本字段），四维过滤；None=不过滤。"""
        doc = self.load()
        rows: list[dict[str, Any]] = []
        for entry in self._entries(doc):
            key = entry.get("key") or {}
            if template_family is not None and \
                    str(key.get("template_family")) != str(template_family):
                continue
            if channel is not None and str(key.get("channel")) != str(channel):
                continue
            for ver in entry.get("versions") or []:
                if status is not None and \
                        str(ver.get("status")) != str(status):
                    continue
                if stale is not None and bool(ver.get("stale")) is not stale:
                    continue
                row = {f: key.get(f) for f in KEY_FIELDS}
                row.update(dict(ver))
                rows.append(row)
        rows.sort(key=lambda r: (
            key_sort_id(r), int(r.get("version") or 0)))
        return rows

    def champion(
        self, key: dict[str, Any],
    ) -> dict[str, Any]:
        """同键非 stale champion 查找（读取面守卫，spec §6.2-2①）。

        Returns:
            ``{"ok": True, "entry": {...}}`` 或
            ``{"ok": False, "reason": "no_champion"|"stale",
            "stale_reason": ...}``——stale champion 拒用并带锚指针。
        """
        doc = self.load()
        entry = self._find_entry(doc, key)
        if entry is None:
            return {"ok": False, "reason": "no_champion",
                    "detail": "键无任何版本"}
        for ver in entry.get("versions") or []:
            if str(ver.get("status")) != STATUS_CHAMPION:
                continue
            if bool(ver.get("stale")):
                return {"ok": False, "reason": "stale",
                        "stale_reason": ver.get("stale_reason"),
                        "entry": dict(ver)}
            return {"ok": True, "entry": dict(ver)}
        return {"ok": False, "reason": "no_champion",
                "detail": "键无 champion 状态版本"}

    # ── 变更面（全部持锁）───────────────────────────────────────────────────

    def upsert(
        self,
        *,
        key: dict[str, Any],
        model: Any = None,
        model_bytes: bytes | None = None,
        heldout: dict[str, Any],
        hyperparams: dict[str, Any] | None = None,
        trained_run_ids: list[str] | None = None,
        render_commit: str | None = None,
        promote: bool = False,
        version: int | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """注册新版本或原位重登记（幂等，spec §6.3-4）。

        - ``heldout`` 强制字段（无 heldout 不入注册表——防"不可评"模型进
          champion 位）；结构 ``{metric, value, n_points}``；
        - ``version=None``：键内 max+1 分配；同键最新版本 blob/超参/heldout
          全同 → 幂等返回既有版本不膨胀；
        - ``version=显式``：存在则原位替换（不膨胀），不存在则插入；
        - champion 策略：键无 champion → 新版本即 champion；已有 champion →
          新版本为 challenger，``promote=True`` 才接管（旧 champion 降
          challenger，MLflow 挑战语义）。
        """
        _require_heldout(heldout)
        if model is None and model_bytes is None:
            raise ValueError("model / model_bytes 至少给一个")
        data = bytes(model_bytes) if model_bytes is not None \
            else pickle.dumps(model)
        commit = render_commit if render_commit is not None else current_git_sha()
        kid = key_sort_id(key)

        with self._locked():
            doc = self.load()
            entry = self._find_entry(doc, key)
            if entry is None:
                entry = {"key": {f: key[f] for f in KEY_FIELDS},
                         "versions": []}
                self._entries(doc).append(entry)
                self._entries(doc).sort(key=lambda e: key_sort_id(e.get("key") or {}))
            versions: list[dict[str, Any]] = entry.setdefault("versions", [])

            sha, blob_display = self._store_blob(data)

            if version is None:
                latest = versions[-1] if versions else None
                if latest is not None and self._same_content(
                        latest, sha, hyperparams, heldout):
                    return {"ok": True, "deduped": True, "entry": dict(latest),
                            "version": latest.get("version")}
                next_ver = max((int(v.get("version") or 0) for v in versions),
                               default=0) + 1
                status = self._assign_status(versions, promote=promote)
                record = self._make_record(
                    next_ver, sha, blob_display, heldout, hyperparams,
                    trained_run_ids, commit, created_at, status)
                versions.append(record)
            else:
                ver_int = int(version)
                status = self._assign_status(versions, promote=promote)
                record = self._make_record(
                    ver_int, sha, blob_display, heldout, hyperparams,
                    trained_run_ids, commit, created_at, status)
                replaced = False
                for i, v in enumerate(versions):
                    if int(v.get("version") or 0) == ver_int:
                        versions[i] = record
                        replaced = True
                        break
                if not replaced:
                    versions.append(record)
                versions.sort(key=lambda v: int(v.get("version") or 0))

            versions.sort(key=lambda v: int(v.get("version") or 0))
            self._save(doc)
            return {"ok": True, "deduped": False, "entry": dict(record),
                    "version": record["version"], "key_id": kid}

    @staticmethod
    def _same_content(
        record: dict[str, Any], sha: str,
        hyperparams: dict[str, Any] | None, heldout: dict[str, Any],
    ) -> bool:
        return (
            str(record.get("model_blob_sha256")) == sha
            and (record.get("hyperparams") or {}) == dict(hyperparams or {})
            and (record.get("heldout") or {}) == dict(heldout)
        )

    @staticmethod
    def _assign_status(
        versions: list[dict[str, Any]], *, promote: bool,
    ) -> str:
        # 键内无任何 champion（含 stale champion——漂移后重训不静默顶替，
        # 须显式 promote 复验通过语义，spec §6.2-2②）→ 新版本自动 champion
        has_champion = any(
            str(v.get("status")) == STATUS_CHAMPION for v in versions)
        if promote or not has_champion:
            # 接管/首版：旧 champion 降 challenger
            for v in versions:
                if str(v.get("status")) == STATUS_CHAMPION:
                    v["status"] = STATUS_CHALLENGER
            return STATUS_CHAMPION
        return STATUS_CHALLENGER

    @staticmethod
    def _make_record(
        version: int,
        sha: str,
        blob_display: str,
        heldout: dict[str, Any],
        hyperparams: dict[str, Any] | None,
        trained_run_ids: list[str] | None,
        render_commit: str | None,
        created_at: str | None,
        status: str,
    ) -> dict[str, Any]:
        return {
            "version": int(version),
            "model_blob_sha256": sha,
            "blob_path": blob_display,
            "trained_run_ids": [str(r) for r in (trained_run_ids or [])],
            "render_commit": render_commit,
            "hyperparams": dict(hyperparams or {}),
            "heldout": dict(heldout),
            "created_at": created_at or utc_now_iso(),
            "status": status,
            "stale": False,
            "stale_reason": None,
        }

    def mark_family_stale(
        self, template_family: str, stale_reason: str,
    ) -> dict[str, Any]:
        """族级漂移失效：同 template_family 全版本标 stale（§6.2-2②）。

        幂等：重复标记更新 stale_reason 不膨胀；retired 版本同样标记
        （spec 原文"全版本"；retired 本就不被消费，标记无副作用）。
        """
        reason = str(stale_reason)
        with self._locked():
            doc = self.load()
            n_marked = 0
            for entry in self._entries(doc):
                key = entry.get("key") or {}
                if str(key.get("template_family")) != str(template_family):
                    continue
                for ver in entry.get("versions") or []:
                    ver["stale"] = True
                    ver["stale_reason"] = reason
                    n_marked += 1
            if n_marked:
                self._save(doc)
            return {"ok": True, "n_marked": n_marked, "stale_reason": reason}

    def set_version_status(
        self, key: dict[str, Any], version: int, status: str,
        *, clear_stale: bool = False,
    ) -> dict[str, Any]:
        """版本状态机（promote/retire 单源；promote 清 stale=复验通过语义）。"""
        if status not in (STATUS_CHAMPION, STATUS_CHALLENGER, STATUS_RETIRED):
            raise ValueError(f"未知状态: {status}")
        with self._locked():
            doc = self.load()
            entry = self._find_entry(doc, key)
            if entry is None:
                return {"ok": False, "reason": "no_entry"}
            target = None
            for ver in entry.get("versions") or []:
                if int(ver.get("version") or 0) == int(version):
                    target = ver
                elif status == STATUS_CHAMPION and \
                        str(ver.get("status")) == STATUS_CHAMPION:
                    ver["status"] = STATUS_CHALLENGER
            if target is None:
                return {"ok": False, "reason": "no_version",
                        "detail": f"version {version} 不存在"}
            target["status"] = status
            if clear_stale:
                target["stale"] = False
                target["stale_reason"] = None
            self._save(doc)
            return {"ok": True, "entry": dict(target)}


def _require_heldout(heldout: Any) -> None:
    """heldout 强制字段校验（无 heldout 不入注册表，spec §6.2-3）。"""
    if not isinstance(heldout, dict):
        raise ValueError("heldout 强制字段缺失（无 heldout 不入注册表）")
    metric = heldout.get("metric")
    value = heldout.get("value")
    n_points = heldout.get("n_points")
    if not isinstance(metric, str) or not metric:
        raise ValueError("heldout.metric 须为非空字符串")
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or value != value or value in (float("inf"), float("-inf")):
        raise ValueError("heldout.value 须为有限数值")
    if isinstance(n_points, bool) or not isinstance(n_points, int) \
            or n_points < 1:
        raise ValueError("heldout.n_points 须为正整数")


# ─── heldout 确定性内核（铁律 7：数字只出自确定性模型）────────────────────────


def heldout_linf(
    surrogate_kind: str,
    surrogate_config: dict[str, Any] | None,
    samples: list[dict[str, Any]],
    objectives: list[Any],
    *,
    frac: float = 0.25,
    min_train: int = 4,
) -> dict[str, Any] | None:
    """留出集 linf 评估（heldout 强制字段的确定性内核）。

    - 确定性切分：按 params canonical json 排序，尾部 ``ceil(n·frac)``
      为 heldout（与采集序/时序无关，同输入同切分）；
    - 训练子集重拟合同 kind 代理 → heldout 逐点预测 metrics →
      SpecEvaluator 转 cost → linf=max|pred−true|；
    - 样本不足（训练子集 < min_train 或无一可用指标）→ 返回 None
      （调用方不得伪造数值——无 heldout 不入注册表）。
    """
    from rfauto.core.objectives import SpecEvaluator
    from rfauto.optimization.surrogate import surrogate_registry

    n = len(samples)
    if n <= min_train:
        return None
    n_hold = max(1, round(n * float(frac)))
    if n - n_hold < min_train:
        return None

    def _sort_key(s: dict[str, Any]) -> str:
        return json.dumps(s.get("params") or {}, sort_keys=True,
                          ensure_ascii=False)

    ordered = sorted(samples, key=_sort_key)
    hold, train = ordered[-n_hold:], ordered[:-n_hold]

    cfg = deepcopy(surrogate_config or {})
    cfg["bounds"] = {k: tuple(v) for k, v in (cfg.get("bounds") or {}).items()}
    model = surrogate_registry.create(surrogate_kind, config=cfg)
    model.fit([
        {"params": dict(s["params"]), "metrics": dict(s.get("metrics") or {})}
        for s in train])
    if not getattr(model, "fitted", False):
        return None

    errs: list[float] = []
    for s in hold:
        try:
            pred = model.predict(dict(s["params"]))
            pred_cost = float(
                SpecEvaluator.evaluate_objectives(pred, objectives))
        except Exception:
            return None  # 预测不可得=heldout 不可评，如实 None 不凑数
        errs.append(abs(pred_cost - float(s["cost"])))
    if not errs:
        return None
    return {"metric": "linf", "value": float(max(errs)),
            "n_points": len(hold)}


def upsert_from_surrogate_loop(
    *,
    model: Any,
    samples: list[dict[str, Any]],
    bounds: dict[str, Any],
    objectives: list[Any],
    surrogate_kind: str,
    surrogate_config: dict[str, Any] | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """训练收尾 upsert（run_surrogate_loop 尾钩消费；heldout 强制）。

    meta 键：template_family / channel 必填；trained_run_ids、preprocessing、
    registry_path、store_dir、render_commit 可选。任何失败以
    ``{"ok": False, "reason": ...}`` 返回（调用方 best-effort #105）。
    """
    try:
        family = str(meta.get("template_family") or "")
        channel = str(meta.get("channel") or "")
        if not family or not channel:
            return {"ok": False,
                    "reason": "registry_meta 缺 template_family/channel"}
        heldout = heldout_linf(
            surrogate_kind, surrogate_config, samples, objectives)
        if heldout is None:
            return {"ok": False, "reason": "insufficient_samples_for_heldout",
                    "n_samples": len(samples)}
        feature_names = [str(k) for k in bounds]
        fingerprint = feature_set_fingerprint(
            feature_names, meta.get("preprocessing"))
        key = canonical_key(family, channel, fingerprint)
        hyper = {"kind": surrogate_kind, **{
            k: v for k, v in (surrogate_config or {}).items()
            if isinstance(v, (int, float, str, bool)) or v is None}}
        reg = ModelRegistry(
            registry_path=meta.get("registry_path"),
            store_dir=meta.get("store_dir"))
        res = reg.upsert(
            key=key,
            model=model,
            heldout=heldout,
            hyperparams=hyper,
            trained_run_ids=meta.get("trained_run_ids"),
            render_commit=meta.get("render_commit"),
        )
        res["heldout"] = heldout
        res["key"] = key
        return res
    except Exception as exc:  # 注册失败不阻塞战役（#105）
        return {"ok": False, "reason": "registry_upsert_failed",
                "detail": f"{exc}"}
