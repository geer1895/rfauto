"""DP-9 P1：DAG 级内容寻址缓存（键 + CAS manifest + 零拷贝索引）。

规格=docs/plan_deepdive_specs_20260924.md §DP-9 §3。核心事实（接地已钉）：
**runs/ 湖已是事实 CAS——本模块只建索引，零拷贝**（runs/ 证据面零改写；
infra/result_cache.py 零 hunk——DAG 键成分名不同，白名单与理由表本地定义，
canonical/模式语义只读复用）。

三载体：
- ``runs/<run>/dag.artifact.json``：产物 digest 清单 + complete 标记
  （Snakemake metadata 借鉴；原子写 tmp+os.replace）；
- ``.rfauto_cache/dag/<key>.json``：键索引（追加不改不删；指向原 run_dir
  零拷贝引用）；``.rfauto_cache/`` 已在 .gitignore（P2 时代条目）。
- 键：render 键 / solve 键 / 通用节点键（成分分列，why_miss 可定位）。

命中校验（Nextflow"hash 命中还要产物在盘"加强版）：键命中→读索引→
manifest 存在且 complete→逐文件重算 sha256 比对→全对才 hit（引用原
run_dir）。缺戳 / incomplete / digest 败一律 miss（自动重跑语义由
pipeline.dag_runner 消费）。

写序（incomplete 语义）：先产物 → 再 dag.artifact.json（原子）→ 最后索引；
中途死在任意一步都不得判 hit（判据 ④）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from rfauto.infra.result_cache import ResultCache

#: runs/<run>/ 内的产物清单文件名（runs/ 证据面增量文件，零改写既有文件）。
ARTIFACT_MANIFEST_NAME = "dag.artifact.json"
ARTIFACT_SCHEMA = "rfauto-dag-artifact-v1"

#: 索引 schema 串（.rfauto_cache/dag/<key>.json）。
INDEX_SCHEMA = "rfauto-dag-index-v1"

#: rerun-trigger 类别 → 键成分（dag_schema.RERUN_TRIGGER_CATEGORIES 的消费面：
#: 关掉某类别 = 该类别成分不进有效键，变化不触发重跑）。
TRIGGER_OF_COMPONENT: dict[str, str] = {
    "render_script_sha": "code",
    "registration_commit_ts": "code",
    "params_canonical_json": "params",
    "upstream_keys": "params",        # 上游键变=上游 params/code 面变（递归传导）
    "mesh_config": "budget",
    "budget_tier": "budget",
    "engine_version": "env",
    "env_fingerprint_sha": "env",
}

#: 键成分 → why_miss 人类可读理由（复用 result_cache.INVALIDATION_REASONS
#: 的模式；成分名不同故本地成表，避免动共享面）。
INVALIDATION_REASONS: dict[str, str] = {
    "render_script_sha": "渲染脚本内容变化（建模脚本已改）",
    "registration_commit_ts": "名义注册 commit 时戳变化（模板/名义几何已重注册）",
    "params_canonical_json": "设计参数变化",
    "mesh_config": "网格配置变化（网格是数值实验的一部分）",
    "engine_version": "引擎版本指纹变化",
    "env_fingerprint_sha": "环境指纹变化（git_sha/pip_freeze/uv.lock）",
    "render_artifact_sha256": "渲染产物变化（上游几何已变）",
    "budget_tier": "预算档变化（不同 NrTS/时窗产物不可互串，#343/#262 族）",
    "upstream_keys": "上游节点键变化（递归重算传导）",
    "input_digests": "输入文件 digest 变化",
    "cmd": "命令声明变化",
}

RENDER_KEY_FIELDS: tuple[str, ...] = (
    "render_script_sha", "registration_commit_ts", "params_canonical_json",
    "mesh_config", "engine_version")
SOLVE_KEY_FIELDS: tuple[str, ...] = (
    "render_artifact_sha256", "engine_version", "budget_tier")
NODE_KEY_FIELDS: tuple[str, ...] = (
    "input_digests", "params_canonical_json", "cmd", "env_fingerprint_sha")

_KEY_PAYLOAD_KIND = {
    "render": "rfauto.dag.render_key.v1",
    "solve": "rfauto.dag.solve_key.v1",
    "node": "rfauto.dag.node_key.v1",
}


def canonical_json(obj: Any) -> str:
    """稳定 JSON 串（复用 ResultCache.canonical_json——只读复用，零 hunk）。"""
    return ResultCache.canonical_json(obj)


def file_sha256(path: str | Path) -> str:
    """文件流式 SHA-256（十六进制）。文件不存在/不可读 → ""（best-effort，
    上层把空 digest 当校验失败处理，不吞错误也不抛穿）。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """UTF-8 文本摘要（与 result_cache.sha256_text 同口径）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─── 环境指纹（规格 §3：collect_provenance 复用 + uv.lock sha256）──────────

def uv_lock_sha256(repo_root: str | Path | None = None) -> str:
    """uv.lock 的 SHA-256（缺失 → ""；best-effort #105，不阻塞键计算）。"""
    root = Path(repo_root) if repo_root else _repo_root_guess()
    lock = root / "uv.lock"
    if not lock.is_file():
        return ""
    return file_sha256(lock)


def env_fingerprint(
    repo_root: str | Path | None = None,
    *,
    solver_versions: dict[str, str] | None = None,
) -> dict[str, str]:
    """环境指纹 dict：git_sha + pip_freeze_sha（collect_provenance 复用）+
    uv.lock sha256。全部 best-effort（#105）：缺失 → 空串，键仍确定性。"""
    try:
        from rfauto.infra.run_store import collect_provenance
        prov = collect_provenance(solver_versions=solver_versions)
    except Exception:                      # pragma: no cover - 防御性
        prov = {"git_sha": "", "pip_freeze_sha": ""}
    return {
        "git_sha": str(prov.get("git_sha", "") or ""),
        "pip_freeze_sha": str(prov.get("pip_freeze_sha", "") or ""),
        "uv_lock_sha256": uv_lock_sha256(repo_root),
    }


def _repo_root_guess() -> Path:
    """仓根推断（本文件位于 <root>/src/rfauto/infra/）。"""
    return Path(__file__).resolve().parents[3]


def registration_commit_ts(
    source_path: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> str:
    """渲染源文件的末次 git commit 时戳（registration_freshness 先例：
    scripts/c3_redesign_synthesis.nominal_commit_ts 同语义——名义注册
    commit 时戳进键，模板重注册即失效旧渲染缓存）。best-effort：非 git
    环境/文件未跟踪 → ""（键成分退化为空串，同环境内仍确定性）。"""
    path = Path(source_path) if source_path else None
    if path is None:
        return ""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(path)],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_root or _repo_root_guess()))
        ts = (out.stdout or "").strip()
        return ts if out.returncode == 0 and ts.isdigit() else ""
    except Exception:
        return ""


# ─── 键计算（成分分列；rerun_triggers 过滤 = 有效键）────────────────────────

def normalize_components(fields: dict[str, Any]) -> dict[str, str]:
    """键成分归一化：None→""，dict→canonical_json，其余必须 str（可复现）。"""
    out: dict[str, str] = {}
    for name in sorted(fields):
        value = fields[name]
        if value is None:
            value = ""
        if isinstance(value, dict):
            value = canonical_json(value)
        if not isinstance(value, str):
            raise TypeError(
                f"缓存键成分 {name!r} 必须是字符串（或 dict），"
                f"收到 {type(value).__name__}")
        out[name] = value
    return out


def effective_components(
    components: dict[str, str], triggers: list[str] | tuple[str, ...]
) -> dict[str, str]:
    """按 rerun_triggers 过滤出进键的成分（缺省全开=全成分=规格键公式）。"""
    wanted = set(triggers)
    return {name: value for name, value in sorted(components.items())
            if TRIGGER_OF_COMPONENT.get(name, "params") in wanted}


def compute_key(kind: str, components: dict[str, str]) -> str:
    """内容寻址键：SHA-256 over canonical{"kind": 载体版本, "components"}。"""
    payload = {"kind": _KEY_PAYLOAD_KIND[kind],
               "version": 1,
               "components": normalize_components(components)}
    return sha256_text(canonical_json(payload))


def render_components(
    *,
    render_script: str | None = None,
    render_script_sha: str = "",
    registration_commit_ts: str = "",
    params_canonical_json: str = "",
    mesh_config: Any = None,
    engine_version: str = "",
) -> dict[str, str]:
    """render 键成分（规格 §3：脚本内容 sha + 注册 commit ts + 参数
    canonical JSON + mesh 配置 + 引擎版本指纹）。render_script 与
    render_script_sha 二选一（前者就地哈希）。"""
    if not render_script_sha:
        render_script_sha = sha256_text(render_script or "")
    mesh_str = "" if mesh_config is None else (
        mesh_config if isinstance(mesh_config, str)
        else canonical_json(mesh_config))
    return normalize_components({
        "render_script_sha": render_script_sha,
        "registration_commit_ts": registration_commit_ts,
        "params_canonical_json": params_canonical_json,
        "mesh_config": mesh_str,
        "engine_version": engine_version,
    })


def solve_components(
    *,
    render_artifact_sha256: str = "",
    engine_version: str = "",
    budget_tier: Any = None,
) -> dict[str, str]:
    """solve 键成分（规格 §3：渲染产物 sha256 + 引擎版本 + 预算档）。

    预算档必须进键（规格 §6 风险条：杜绝不同 NrTS 时窗产物互串，
    #343/#262 族）。"""
    tier_str = "" if budget_tier is None else (
        budget_tier if isinstance(budget_tier, str)
        else canonical_json(budget_tier))
    return normalize_components({
        "render_artifact_sha256": render_artifact_sha256,
        "engine_version": engine_version,
        "budget_tier": tier_str,
    })


def node_components(
    *,
    input_digests: str = "",
    params_canonical_json: str = "",
    cmd: str = "",
    env_fingerprint_sha: str = "",
) -> dict[str, str]:
    """通用节点键成分（postprocess/judge：输入 digest+参数+cmd+环境指纹）。

    upstream_keys 不在此处——它由 pipeline.dag_runner 拼进有效键载荷
    （上上游变化经上游键传导，不必重复进成分表）。"""
    return normalize_components({
        "input_digests": input_digests,
        "params_canonical_json": params_canonical_json,
        "cmd": cmd,
        "env_fingerprint_sha": env_fingerprint_sha,
    })


def compute_node_key(
    kind: str,
    components: dict[str, str],
    *,
    node_id: str = "",
    triggers: list[str] | tuple[str, ...] | None = None,
    upstream_keys: dict[str, str] | None = None,
) -> str:
    """节点有效键 = hash(载体 kind + 触发器过滤后的成分 + 上游有效键)。

    triggers=None → 全开（不过滤，规格键公式原样）；triggers 给定 → 按
    TRIGGER_OF_COMPONENT 类别过滤（关掉的类别不进键）。上游键进载荷 ⇒
    篡改上游产物字节 → 上游键变（digest 败重跑后新产物 digest 变）→
    下游键变递归重算（判据 ③ 传导语义的落点）。"""
    comps = dict(components)
    if upstream_keys:
        comps["upstream_keys"] = canonical_json(
            {k: upstream_keys[k] for k in sorted(upstream_keys)})
    filtered = (comps if triggers is None
                else effective_components(comps, triggers))
    payload = {"kind": _KEY_PAYLOAD_KIND[kind], "version": 1,
               "node_id": node_id, "components": filtered}
    return sha256_text(canonical_json(payload))


def why_miss(
    requested: dict[str, str], stored: dict[str, str] | None
) -> list[str]:
    """miss 理由（best-effort #105）：与最近条目逐成分 diff，套
    INVALIDATION_REASONS；无可比条目时单条说明。"""
    if not stored:
        return ["无历史索引条目可比对（首次执行或索引为空）"]
    reasons: list[str] = []
    for name in sorted(set(requested) | set(stored)):
        old = stored.get(name, "")
        new = requested.get(name, "")
        if old != new:
            reason = INVALIDATION_REASONS.get(name, "成分变化")
            reasons.append(f"{name}: {old[:12]}… -> {new[:12]}… （{reason}）")
    return reasons or ["成分全同但校验未过（产物面损坏，见 digest 校验）"]


# ─── CAS 产物清单（runs/<run>/dag.artifact.json）────────────────────────────

def digest_of_files(
    base_dir: str | Path, relpaths: list[str]
) -> str:
    """文件集 digest：sha256 over "relpath:sha256" 排序行（缺失文件计
    "MISSING"，保证缺文件必然改变 digest——下游键传导不静默）。"""
    lines = []
    for rel in sorted(set(relpaths)):
        digest = file_sha256(Path(base_dir) / rel) or "MISSING"
        lines.append(f"{rel}:{digest}")
    return sha256_text("\n".join(lines))


def write_artifact_manifest(
    run_dir: str | Path,
    files: list[str],
    *,
    complete: bool = True,
    node_id: str = "",
    key: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    """原子写产物清单（先产物、再 manifest、最后索引的**第二步**）。

    tmp + os.replace（单写者原子性，Windows 安全）；complete=False 即
    incomplete 标记（判据 ④：一律 miss）。runs/ 证据面只新增本文件，
    零改写既有文件。"""
    base = Path(run_dir)
    base.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema": ARTIFACT_SCHEMA,
        "complete": bool(complete),
        "node_id": node_id,
        "key": key,
        "files": [{"path": rel, "sha256": file_sha256(base / rel) or "MISSING"}
                  for rel in sorted(set(files))],
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        manifest.update(extra)
    dest = base / ARTIFACT_MANIFEST_NAME
    tmp = base / f"{ARTIFACT_MANIFEST_NAME}.tmp-{os.getpid()}"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1,
                              sort_keys=True), encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def read_artifact_manifest(run_dir: str | Path) -> dict[str, Any] | None:
    """读产物清单（缺失/损坏/非 dict → None = never-hit 口径）。"""
    path = Path(run_dir) / ARTIFACT_MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def verify_artifacts(
    run_dir: str | Path, manifest: dict[str, Any] | None = None
) -> tuple[bool, list[str]]:
    """逐文件重算 sha256 比对清单（Nextflow 加强版校验）。

    返回 (ok, problems)：manifest 缺失 / complete=False / 任一文件缺失或
    digest 不符 → (False, 问题清单)。digest="MISSING"=文件缺失。"""
    run_path = Path(run_dir)
    if manifest is None:
        manifest = read_artifact_manifest(run_path)
    if manifest is None:
        return False, ["产物清单缺失（旧档无 manifest=never-hit）"]
    if manifest.get("complete") is not True:
        return False, ["产物清单带 incomplete 标记（半产物一律 miss）"]
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        return False, ["产物清单无文件条目"]
    problems: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append("清单条目非法（非 dict）")
            continue
        rel = str(entry.get("path", ""))
        want = str(entry.get("sha256", ""))
        got = file_sha256(run_path / rel) or "MISSING"
        if got != want:
            problems.append(f"{rel}: digest 不符（清单 {want[:12]}… 实测 {got[:12]}…）")
    return (not problems), problems


# ─── 零拷贝索引（.rfauto_cache/dag/<key>.json，只增不改不删）────────────────

class DagCasIndex:
    """DAG 产物索引：键 → 原 run_dir 的零拷贝引用。

    模式沿用 ResultCache 的 RFAUTO_CACHE 语义（off/readonly/readwrite）。
    **只增不改不删**：store 对已存在键不覆写（键是内容地址，重复 store
    同键即同内容；首个索引持有者保留）。
    """

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = (Path(cache_dir) if cache_dir
                          else Path(".rfauto_cache") / "dag")
        mode = os.environ.get("RFAUTO_CACHE", "readwrite").lower()
        if mode not in ("off", "readonly", "readwrite"):
            mode = "readwrite"
        self._mode = mode
        self.enabled = mode != "off"
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _entry_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def store_index(
        self,
        key: str,
        *,
        run_dir: str | Path,
        node_kind: str = "",
        components: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path | None:
        """写索引条目（第三步；readwrite 才写）。已存在 → 不覆写只增不改。

        返回条目路径；旁路模式返回 None。注意：**调用方必须已写完
        dag.artifact.json**（写序合约，本方法不校验——执行层
        pipeline.dag_runner 负责次序）。"""
        if self._mode != "readwrite":
            return None
        entry = {
            "schema": INDEX_SCHEMA,
            "key": key,
            "node_kind": node_kind,
            "run_dir": str(Path(run_dir)),
            "components": dict(components or {}),
            "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if extra:
            entry.update(extra)
        path = self._entry_path(key)
        if path.exists():                      # 只增不改不删
            return path
        tmp = self.cache_dir / f"{key}.tmp-{os.getpid()}"
        tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=1,
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def read_index(self, key: str) -> dict[str, Any] | None:
        """读索引条目（缺失/损坏 → None）。"""
        path = self._entry_path(key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def lookup(
        self,
        key: str,
        *,
        node_kind: str = "",
        components: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """完整命中校验（规格 §3）：

        键命中（索引存在）→ run_dir 的 manifest 存在且 complete →
        逐文件重算 sha256 → 全对 = hit（path=原 run_dir 零拷贝引用）。
        任何一步失败 = miss，why_miss 非空（判据 ③④）。"""
        result: dict[str, Any] = {
            "hit": False, "key": key, "path": None, "run_dir": None,
            "why_miss": [],
        }
        if not self.enabled:
            result["why_miss"] = ["缓存已旁路（RFAUTO_CACHE=off）"]
            return result
        entry = self.read_index(key)
        if entry is None:
            stored = self._nearest_entry(components)
            if components and stored is not None:
                result["why_miss"] = why_miss(components, stored)
            else:
                result["why_miss"] = ["索引无此键（首次执行或索引为空）"]
            return result
        run_dir = str(entry.get("run_dir", "") or "")
        manifest = read_artifact_manifest(run_dir) if run_dir else None
        if manifest is None:
            result["why_miss"] = ["run_dir 无产物清单（旧档无 manifest=never-hit）"]
            return result
        ok, problems = verify_artifacts(run_dir, manifest)
        if not ok:
            result["why_miss"] = problems
            return result
        result.update({
            "hit": True,
            "path": run_dir,
            "run_dir": run_dir,
            "node_kind": entry.get("node_kind", ""),
            "manifest": manifest,
        })
        return result

    def _nearest_entry(
        self, components: dict[str, str] | None
    ) -> dict[str, str] | None:
        """扫索引找与请求成分差异最小的一条（why_miss 比对面，best-effort）。"""
        if not components or not self.cache_dir.is_dir():
            return None
        best: tuple[int, dict[str, str]] | None = None
        for child in sorted(self.cache_dir.glob("*.json")):
            if child.name.endswith(".tmp-*"):
                continue
            try:
                data = json.loads(child.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            stored = data.get("components") if isinstance(data, dict) else None
            if not isinstance(stored, dict):
                continue
            diffs = sum(1 for name in set(components) | set(stored)
                        if stored.get(name, "") != components.get(name, ""))
            if best is None or diffs < best[0]:
                best = (diffs, {k: str(v) for k, v in stored.items()})
        return best[1] if best else None
