"""reproducibility_service：G7 可复现性清单（环境 + 依赖锁 + 结果哈希 + 校验）。

面向发布/复现提供**确定性**清单，全部纯 Python 标准库实现（不依赖 Docker）：

- 环境清单 collect_environment_manifest：Python 版本、平台、关键依赖版本
  （importlib.metadata）、git 提交（best-effort，取不到退化为 None 而不抛
  异常）；**不写时间戳**——时间戳会让清单每次不同，与"两次一致"的验收
  口径直接冲突；
- 依赖锁摘要 dependency_lock_digest：声明依赖集合 {name: version} 排序后
  canonical JSON → sha256（与字典插入顺序无关）；依赖集合变化必然改变摘要；
- 结果哈希 build_artifact_manifest：文件按相对 POSIX 路径排序，逐个内容
  sha256，再对 {rel: digest} 清单做一次 sha256。**只哈希内容**，mtime/size
  等易变元数据天然不参与；需要忽略的路径必须由 ignore 参数显式列出并回写
  清单（审计可见，不隐式丢弃）；
- 校验 verify_artifact_manifest / verify_reproducibility_manifest：给定清单
  + 当前目录，报 missing / changed / extra 三态差异，顺序确定（sorted）。

设计约束（best-effort 纪律）：环境探测（git/包版本）全部 best-effort，失败退化
为 None；但**入参非法**（类型错、空依赖集、清单缺字段）显式 ValueError，
绝不静默产出无意义摘要。缺路径属于数据态，返回 {"ok": False, "errors": [...]}。

如实记未做：Docker 镜像构建/镜像内干净 venv 重放（本机无 Docker，模块设计本身不依赖 Docker）。
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
HASH_ALGORITHM = "sha256"

# 环境清单默认采集的核心依赖（与 pyproject [project].dependencies 对齐）
DEFAULT_KEY_DEPENDENCIES: tuple[str, ...] = (
    "pydantic",
    "omegaconf",
    "loguru",
    "rich",
    "typer",
    "numpy",
    "scipy",
    "scikit-rf",
    "matplotlib",
    "pandas",
    "optuna",
    "pytest",
)


def _canonical_json(obj: Any) -> str:
    """确定性 JSON 串：键排序 + 紧凑分隔符 + ASCII 转义。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def _sha256(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return f"{HASH_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


# ─── 依赖锁摘要 ────────────────────────────────────────────────────────────────

def _dependency_names(dependencies: Iterable[str]) -> list[str]:
    """名称可迭代 → 去重排序列表；字符串/非可迭代/空集合显式报错。"""
    if isinstance(dependencies, (str, bytes)):
        raise ValueError("dependencies 需要名称可迭代或 {name: version} 映射，不是字符串")
    try:
        names = sorted({str(n) for n in dependencies})
    except TypeError as exc:
        raise ValueError("dependencies 需要名称可迭代或 {name: version} 映射") from exc
    if not names:
        raise ValueError("dependencies 不能为空（空集合的锁摘要无意义）")
    return names


def _normalize_dependencies(dependencies: Any) -> dict[str, str | None]:
    """依赖集合 → 归一化 {name: version|None}（version None = 未安装/未钉）。"""
    if isinstance(dependencies, Mapping):
        items = {str(k): (None if v is None else str(v)) for k, v in dependencies.items()}
        if not items:
            raise ValueError("dependencies 不能为空（空集合的锁摘要无意义）")
        return items
    return {name: None for name in _dependency_names(dependencies)}


def distribution_versions(dependencies: Any) -> dict[str, str | None]:
    """查询声明依赖的已安装版本；缺失/探测失败一律记为 None（best-effort）。"""
    if isinstance(dependencies, Mapping):
        return _normalize_dependencies(dependencies)

    from importlib.metadata import PackageNotFoundError, version

    result: dict[str, str | None] = {}
    for name in _dependency_names(dependencies):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
        except Exception:  # 环境探测 best-effort，不允许成为故障点
            result[name] = None
    return result


def dependency_lock_digest(dependencies: Any) -> str:
    """声明的依赖集合 → 确定性 sha256 摘要（"sha256:<hex>"）。

    接受 {name: version} 映射或名称可迭代（后者版本记 None）。排序 canonical
    JSON 保证与插入顺序无关；集合或版本任一变化都改变摘要。
    """
    return _sha256(_canonical_json(_normalize_dependencies(dependencies)))


def _requirement_name(spec: str) -> str:
    """PEP 508 需求串 → 规范化的分发名（小写、下划线转连字符）。"""
    name = spec.strip()
    for sep in (";", "[", "(", " ", "<", ">", "=", "!", "~"):
        name = name.split(sep, 1)[0]
    return name.strip().lower().replace("_", "-")


def load_declared_dependencies(pyproject_path: str | Path | None = None) -> dict[str, Any] | None:
    """从 pyproject.toml 读声明的 core/extras 依赖名（best-effort）。

    解析失败/文件缺失/tomllib 不可用（Python 3.10）返回 None，调用方自行
    回退到常量集合。返回 {"core": [...], "extras": {group: [...]}}。
    """
    try:
        import tomllib
    except ImportError:
        return None

    path = Path(pyproject_path) if pyproject_path is not None else Path("pyproject.toml")
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None

    project = data.get("project")
    if not isinstance(project, Mapping):
        return None
    core = [_requirement_name(s) for s in project.get("dependencies") or [] if isinstance(s, str)]
    extras_raw = project.get("optional-dependencies") or {}
    extras: dict[str, list[str]] = {}
    if isinstance(extras_raw, Mapping):
        for group, specs in extras_raw.items():
            extras[str(group)] = [_requirement_name(s) for s in specs or [] if isinstance(s, str)]
    return {"core": core, "extras": extras}


# ─── 环境清单 ──────────────────────────────────────────────────────────────────

def _git_provenance(repo: str | Path | None = None) -> dict[str, Any]:
    """git commit/dirty 探测（best-effort，任何失败退化为 None）。"""
    provenance: dict[str, Any] = {"commit": None, "dirty": None}
    cwd = str(repo) if repo is not None else None
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                              capture_output=True, text=True, timeout=10, check=False)
        if head.returncode == 0:
            provenance["commit"] = head.stdout.strip() or None
        status = subprocess.run(["git", "status", "--porcelain"], cwd=cwd,
                                capture_output=True, text=True, timeout=10, check=False)
        if status.returncode == 0:
            provenance["dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return provenance


def collect_environment_manifest(
    *,
    dependencies: Any = None,
    include_git: bool = True,
    git_repo: str | Path | None = None,
) -> dict[str, Any]:
    """采集环境清单（确定性：同进程两次调用逐字段一致）。

    dependencies：None → DEFAULT_KEY_DEPENDENCIES；映射 → 直接作为已钉版本；
    可迭代 → 查询 importlib.metadata 版本。
    """
    if dependencies is None:
        packages = distribution_versions(DEFAULT_KEY_DEPENDENCIES)
    else:
        packages = distribution_versions(dependencies)

    return {
        "schema_version": SCHEMA_VERSION,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": packages,
        "lock_digest": dependency_lock_digest(packages),
        "git": _git_provenance(git_repo) if include_git else {"commit": None, "dirty": None},
        "generated_by": "rfauto.service.reproducibility_service",
    }


# ─── 结果哈希（产物清单）───────────────────────────────────────────────────────

def _resolve_target(target: Any) -> Path:
    """路径入参收敛；非路径类型显式 ValueError（#140 风格：注解不代表实参）。"""
    if target is None or isinstance(target, bool):
        raise ValueError(f"target 需要路径，收到: {target!r}")
    try:
        return Path(target)
    except TypeError as exc:
        raise ValueError(f"target 需要路径，收到: {target!r}") from exc


def _normalize_ignore(ignore: Any) -> tuple[str, ...]:
    if ignore is None:
        return ()
    if isinstance(ignore, str):
        patterns: tuple[str, ...] = (ignore,)
    else:
        try:
            patterns = tuple(str(p) for p in ignore)
        except TypeError as exc:
            raise ValueError("ignore 需要 glob 字符串或字符串可迭代") from exc
    return tuple(p for p in patterns if p)


def _iter_files(base: Path) -> list[tuple[str, Path]]:
    """(相对 POSIX 路径, 绝对路径) 列表，按相对路径排序。"""
    if base.is_file():
        return [(base.name, base)]
    pairs = [(p.relative_to(base).as_posix(), p) for p in base.rglob("*") if p.is_file()]
    pairs.sort(key=lambda item: item[0])
    return pairs


def _is_ignored(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def build_artifact_manifest(target: str | Path, *, ignore: Any = ()) -> dict[str, Any]:
    """对 run 目录/产物文件求确定性结果清单（含逐文件哈希与总体摘要）。

    只哈希文件内容：mtime/size 等易变元数据不参与，因此同内容重写摘要不变。
    ignore：相对路径 glob（如 "*.log"），显式列出并回写清单。路径不存在 →
    {"ok": False, "errors": [...]}（数据态）；target 类型非法 → ValueError。
    """
    base = _resolve_target(target)
    if not base.exists():
        return {"ok": False, "errors": [f"目标不存在: {base}"]}
    patterns = _normalize_ignore(ignore)

    entries: dict[str, str] = {}
    for rel, path in _iter_files(base):
        if _is_ignored(rel, patterns):
            continue
        try:
            entries[rel] = _sha256(path.read_bytes())
        except OSError as exc:
            return {"ok": False, "errors": [f"读取失败: {rel}: {exc}"]}

    ordered = dict(sorted(entries.items()))
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "root": str(base),
        "files": ordered,
        "file_count": len(ordered),
        "digest": _sha256(_canonical_json(ordered)),
        "ignored": list(patterns),
    }


def _manifest_files(manifest: Any) -> dict[str, str]:
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest 需要映射")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise ValueError("manifest 缺少 files 映射")
    return {str(k): str(v) for k, v in files.items()}


def verify_artifact_manifest(manifest: Any, target: str | Path) -> dict[str, Any]:
    """给定产物清单 + 当前目录 → missing/changed/extra 三态差异（确定性排序）。"""
    if not isinstance(manifest, Mapping):
        return {"ok": False, "errors": ["manifest 需要映射"],
                "missing": [], "changed": [], "extra": []}
    try:
        recorded = _manifest_files(manifest)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)],
                "missing": [], "changed": [], "extra": []}

    ignore = manifest.get("ignored") or ()
    current = build_artifact_manifest(target, ignore=ignore)
    if not current.get("ok"):
        return {"ok": False, "errors": list(current.get("errors", [])),
                "missing": [], "changed": [], "extra": []}

    current_files: dict[str, str] = current["files"]
    recorded_keys = set(recorded)
    current_keys = set(current_files)
    missing = sorted(recorded_keys - current_keys)
    extra = sorted(current_keys - recorded_keys)
    changed = sorted(k for k in (recorded_keys & current_keys) if recorded[k] != current_files[k])
    unchanged = sorted((recorded_keys & current_keys) - set(changed))

    return {
        "ok": not (missing or extra or changed),
        "missing": missing,
        "changed": changed,
        "extra": extra,
        "unchanged": unchanged,
        "recorded_count": len(recorded),
        "current_count": len(current_files),
        "current_digest": current["digest"],
    }


# ─── 环境差异 ──────────────────────────────────────────────────────────────────

def _extract_packages(obj: Any) -> dict[str, str | None] | None:
    if isinstance(obj, Mapping) and isinstance(obj.get("packages"), Mapping):
        return {str(k): (None if v is None else str(v)) for k, v in obj["packages"].items()}
    if isinstance(obj, Mapping):
        return {str(k): (None if v is None else str(v)) for k, v in obj.items()}
    return None


def diff_packages(recorded: Any, current: Any) -> dict[str, Any]:
    """两份 {name: version} 集合 → missing/changed/extra 三态差异。"""
    rec = _extract_packages(recorded)
    cur = _extract_packages(current)
    if rec is None or cur is None:
        raise ValueError("packages 需要 {name: version} 映射（或含 packages 的清单）")
    missing = sorted(set(rec) - set(cur))
    extra = sorted(set(cur) - set(rec))
    changed = sorted(k for k in (set(rec) & set(cur)) if rec[k] != cur[k])
    unchanged = sorted((set(rec) & set(cur)) - set(changed))
    return {"ok": not (missing or changed or extra), "missing": missing,
            "changed": changed, "extra": extra, "unchanged": unchanged}


def verify_environment(recorded: Any, current: Any) -> dict[str, Any]:
    """环境清单差异：packages 三态 + lock_digest 一致性。"""
    rec_pkgs = _extract_packages(recorded)
    cur_pkgs = _extract_packages(current)
    if rec_pkgs is None or cur_pkgs is None:
        return {"ok": False, "errors": ["环境清单缺少 packages 映射"],
                "missing": [], "changed": [], "extra": []}
    report = diff_packages(rec_pkgs, cur_pkgs)
    rec_lock = recorded.get("lock_digest") if isinstance(recorded, Mapping) else None
    cur_lock = current.get("lock_digest") if isinstance(current, Mapping) else None
    if cur_lock is None:
        # 调用方只给了 {name: version} 映射：从 packages 重算摘要再比对
        cur_lock = dependency_lock_digest(cur_pkgs)
    lock_match = rec_lock is None or rec_lock == cur_lock
    report["lock_digest_match"] = lock_match
    report["ok"] = bool(report["ok"]) and lock_match
    return report


# ─── 集成清单（构建 / 校验 / 落盘 / 读回）────────────────────────────────────────

def build_reproducibility_manifest(
    target: str | Path | None = None,
    *,
    dependencies: Any = None,
    ignore: Any = (),
    include_git: bool = True,
    git_repo: str | Path | None = None,
) -> dict[str, Any]:
    """组装完整复现清单：环境段 + 可选产物段。"""
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "environment": collect_environment_manifest(
            dependencies=dependencies, include_git=include_git, git_repo=git_repo),
    }
    if target is not None:
        artifacts = build_artifact_manifest(target, ignore=ignore)
        manifest["artifacts"] = artifacts
        if not artifacts.get("ok"):
            manifest["ok"] = False
            manifest["errors"] = list(artifacts.get("errors", []))
            return manifest
    manifest["ok"] = True
    return manifest


def verify_reproducibility_manifest(
    manifest: Any,
    target: str | Path | None = None,
    *,
    current_environment: Any = None,
) -> dict[str, Any]:
    """校验完整清单：产物三态差异 + 环境 packages/lock 差异。"""
    if not isinstance(manifest, Mapping):
        return {"ok": False, "errors": ["manifest 需要映射"],
                "artifacts": None, "environment": None}

    errors: list[str] = []
    artifact_report: dict[str, Any] | None = None
    environment_report: dict[str, Any] | None = None

    if "artifacts" in manifest:
        if target is None:
            errors.append("清单含 artifacts 段但未提供 target 目录")
        else:
            artifact_report = verify_artifact_manifest(manifest["artifacts"], target)

    env_manifest = manifest.get("environment")
    if isinstance(env_manifest, Mapping) and _extract_packages(env_manifest):
        current = current_environment
        if current is None:
            current = collect_environment_manifest(
                dependencies=tuple(env_manifest["packages"]), include_git=False)
        environment_report = verify_environment(env_manifest, current)

    ok = not errors
    if artifact_report is not None:
        ok = ok and bool(artifact_report.get("ok"))
    if environment_report is not None:
        ok = ok and bool(environment_report.get("ok"))

    return {"ok": ok, "errors": errors,
            "artifacts": artifact_report, "environment": environment_report}


def write_manifest(manifest: Any, path: str | Path) -> dict[str, Any]:
    """清单落盘（键排序 JSON，稳定字节序）；返回路径与清单内容摘要。"""
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest 需要映射")
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return {"ok": True, "path": str(dest), "digest": _sha256(_canonical_json(manifest))}


def read_manifest(path: str | Path) -> dict[str, Any]:
    """读回清单；文件缺失/解析失败 → {"ok": False, "errors": [...]}。"""
    src = Path(path)
    if not src.is_file():
        return {"ok": False, "errors": [f"清单不存在: {src}"]}
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"清单解析失败: {exc}"]}
    if not isinstance(data, Mapping):
        return {"ok": False, "errors": ["清单根节点需要 JSON 对象"]}
    return {"ok": True, "manifest": dict(data)}
