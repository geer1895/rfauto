"""recipes/ 原件写守卫（配方污染根修）。

背景（一次真实污染事故的取证）：
UI 配方页「保存并运行」链曾把 recipes/branchline_coupler_v1.yaml
整文件 ``yaml.safe_dump`` 重序列化后 ``tmp.replace()`` 覆盖原件——注释全丢、
notes 引号丢失、``optimization`` 段被表单归一化结果（``n_trials: null`` /
``sampler: tpe``）整段替换（diff 85 行），随后同刻触发 fake ``run_once``。
``run_once`` 本身只写 ``runs/<id>/recipe.snapshot.yaml``，并非写回点。

根修原则：**任何库代码路径禁写 recipes/ 原件**。所有配方 YAML 写出统一走
本模块出口，按目标路径决策：

- 目标不在受保护 recipes/ 根下 → 原样写出（tmp_path/沙箱/runs/ 等不受影响）。
- 受保护 + ``redirect=True`` → 重定向到 ``runs/recipe_workcopy/<相对路径>``
  工作副本，返回实际写出路径（调用方必须消费返回值；UI 表单保存、autotune
  变体等"从已加载配方自身路径派生目标"的隐式写回一律走此档）。
- 受保护 + ``explicit=True`` → 原地写出。**边界如实**：只给用户把目标路径
  作为命令本意显式指定的入口（``rfauto recipe migrate <path>``、CLI/MCP
  ``--out/--output``、UI 新建向导的用户键入路径）。若覆盖既有原件，返回
  路径带 ``overwritten=True`` 标记（消除与 ui ``recipe_create``
  拒覆盖的不对称盲写，调用方须把标记透传给用户）。
- 受保护且两者皆否 → 抛 :class:`RecipeWriteForbidden`（默认档，抓未来
  新增的隐式写回）。

受保护根 = ``<cwd>/recipes``（仓内 ``Path("recipes")`` 惯例，含测试
chdir 的 tmp_path）∪ 仓库自带 ``recipes/``（进程 chdir 到别处仍受保护）。
非常规序列化器（如 OmegaConf.save）用 :func:`check_recipe_write_target`
先行校验。分层：infra 只依赖标准库 + yaml（core 之上、service 之下）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

WORKCOPY_SUBDIR: tuple[str, ...] = ("runs", "recipe_workcopy")
PROTECTED_DIRNAME = "recipes"


class RecipeWriteForbidden(PermissionError):
    """对受保护 recipes/ 原件的未授权程序化写操作（守卫拒绝）。"""


def _absolute(path: str | Path) -> Path:
    """相对路径按 cwd 收敛；尽量 resolve（跟随符号链接），失败退 absolute。"""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _norm(path: Path) -> Path:
    """比较用规范形（Windows 大小写/分隔符不敏感）。"""
    return Path(os.path.normcase(str(path)))


def protected_recipe_roots() -> tuple[Path, ...]:
    """当前受保护的 recipes/ 根（绝对路径，去重，顺序：cwd 优先）。"""
    roots: list[Path] = [_absolute(Path(PROTECTED_DIRNAME))]
    # src/rfauto/infra/recipe_guard.py → parents[3] = 仓库根
    repo_recipes = Path(__file__).resolve().parents[3] / PROTECTED_DIRNAME
    if _norm(repo_recipes) not in {_norm(r) for r in roots}:
        roots.append(repo_recipes)
    return tuple(roots)


def _rel_parts_under(target: Path, root: Path) -> tuple[str, ...] | None:
    """target 位于 root 下时返回相对分段（保留原始大小写），否则 None。"""
    try:
        rel = _norm(target).relative_to(_norm(root))
    except ValueError:
        return None
    n = len(rel.parts)
    return tuple(target.parts[len(target.parts) - n:]) if n else ()


def is_protected_recipe_path(path: str | Path) -> bool:
    """目标是否落在任一受保护 recipes/ 根下（含根本身）。"""
    target = _absolute(path)
    return any(_rel_parts_under(target, root) is not None
               for root in protected_recipe_roots())


def workcopy_path(path: str | Path) -> Path:
    """受保护配方对应的工作副本路径 ``runs/recipe_workcopy/<相对 recipes 根>``。

    返回 cwd 相对路径（与仓内 ``Path("runs")`` 惯例一致、UI 可读）。
    目标不受保护或恰为 recipes 根本身时抛 :class:`RecipeWriteForbidden`。
    """
    target = _absolute(path)
    for root in protected_recipe_roots():
        rel = _rel_parts_under(target, root)
        if rel is None:
            continue
        if not rel:
            raise RecipeWriteForbidden(f"recipes 根目录本身不是合法配方写目标: {target}")
        return Path(*WORKCOPY_SUBDIR).joinpath(*rel)
    raise RecipeWriteForbidden(f"目标不在受保护 recipes/ 下，无需工作副本: {target}")


def resolve_recipe_write_target(
    path: str | Path,
    *,
    explicit: bool = False,
    redirect: bool = False,
) -> Path:
    """统一写出口决策（守卫核心）——返回**实际应写出的路径**。

    - 不受保护 → 原样返回（保持调用方传入的相对/绝对形态）。
    - 受保护 + explicit → 原样返回（用户显式保存入口）。
    - 受保护 + redirect → 工作副本路径。
    - 受保护且两者皆否 → 抛 :class:`RecipeWriteForbidden`。
    """
    p = Path(path)
    if not is_protected_recipe_path(p):
        return p
    if explicit:
        return p
    if redirect:
        return workcopy_path(p)
    raise RecipeWriteForbidden(
        f"recipes/ 原件禁止程序化改写: {p}（隐式写回请 redirect=True 落 "
        f"{Path(*WORKCOPY_SUBDIR)}/ 工作副本；用户显式保存入口才 explicit=True）")


def check_recipe_write_target(path: str | Path, *, explicit: bool = False) -> Path:
    """非常规序列化器（OmegaConf.save 等）的先行校验：受保护且非显式即抛。"""
    return resolve_recipe_write_target(path, explicit=explicit, redirect=False)


class GuardedWritePath(Path):
    """受保护原件 explicit 写出的返回路径：附 ``overwritten`` 覆盖标记。

    ``overwritten=True`` 表示本次 explicit 写**覆盖**了受保护 recipes/ 根内
    的既有原件（消除与 ui ``recipe_create`` 拒覆盖的不对称盲写）；
    ``False`` 为受保护根内新建。派生路径（``parent``/``with_name`` 等）
    继承本类、标记恒为类缺省 False。非受保护路径照旧返回普通 ``Path``、
    不带标记（保持既有行为，读取方用 ``getattr(p, "overwritten", False)``）。
    """

    overwritten: bool = False


def write_recipe_text(
    path: str | Path,
    text: str,
    *,
    explicit: bool = False,
    redirect: bool = False,
    encoding: str = "utf-8",
) -> Path:
    """守卫化文本写出（自动建父目录），返回实际写出路径。

    受保护 + ``explicit=True`` 时返回 :class:`GuardedWritePath`，其
    ``overwritten`` 属性标示本次显式写是否覆盖了受保护根内的既有原件
    （True=覆盖、False=新建）；其余路径返回普通 ``Path``、不带标记。
    """
    target = resolve_recipe_write_target(path, explicit=explicit, redirect=redirect)
    mark = explicit and is_protected_recipe_path(target)
    overwritten = bool(mark and target.exists())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding=encoding)
    if mark:
        marked = GuardedWritePath(target)
        marked.overwritten = overwritten
        return marked
    return target


def sanitize_numpy_scalars(data: Any) -> Any:
    """递归把 numpy 标量/数组转成 Python 原生类型（值精确保留，返回新容器）。

    背景（fix-tsdraft-npfloat64）：综合内核（skrf/scipy 链）的 ``np.sqrt``/
    ``brentq`` 产物是 ``np.float64``，``round()`` 不改型，经 recipe_draft
    透传到 ``yaml.safe_dump`` 即抛 ``RepresenterError``（branchline
    ``arm_len_mm=18.57`` 实证；wstep/gysel/patch/ratrace/wilkinson 同类泄漏）。
    根修在守卫统一写出出口递归转换，而非逐个综合内核补 ``float()``——
    防未来任何综合器再泄漏。

    转换规则：``np.generic`` → ``.item()``（np.float64→float、np.int64→int、
    np.bool_→bool，值精确）；``np.ndarray`` → ``.tolist()``；dict/list/tuple
    逐元素递归（dict 键为 numpy 标量时一并转）；其余类型原样返回。
    输入不被原地修改。
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy 为项目硬依赖，防御性兜底
        return data
    if isinstance(data, np.generic):
        return data.item()
    if isinstance(data, np.ndarray):
        return data.tolist()
    if isinstance(data, dict):
        return {
            (k.item() if isinstance(k, np.generic) else k): sanitize_numpy_scalars(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [sanitize_numpy_scalars(v) for v in data]
    if isinstance(data, tuple):
        return tuple(sanitize_numpy_scalars(v) for v in data)
    return data


def write_recipe_yaml(
    path: str | Path,
    data: Any,
    *,
    explicit: bool = False,
    redirect: bool = False,
    **dump_kwargs: Any,
) -> Path:
    """守卫化 YAML 写出（缺省 ``allow_unicode=True, sort_keys=False``），返回实际路径。

    payload 先经 :func:`sanitize_numpy_scalars` 递归转换（综合内核
    np 标量泄漏 → ``yaml.safe_dump`` ``RepresenterError`` 的根修出口）。
    返回值语义同 :func:`write_recipe_text`（受保护 + explicit 时带
    ``overwritten`` 标记，见 :class:`GuardedWritePath`）。
    """
    import yaml

    kwargs: dict[str, Any] = {"allow_unicode": True, "sort_keys": False}
    kwargs.update(dump_kwargs)
    return write_recipe_text(path, yaml.safe_dump(sanitize_numpy_scalars(data), **kwargs),
                             explicit=explicit, redirect=redirect)


__all__ = [
    "PROTECTED_DIRNAME",
    "WORKCOPY_SUBDIR",
    "GuardedWritePath",
    "RecipeWriteForbidden",
    "check_recipe_write_target",
    "is_protected_recipe_path",
    "protected_recipe_roots",
    "resolve_recipe_write_target",
    "sanitize_numpy_scalars",
    "workcopy_path",
    "write_recipe_text",
    "write_recipe_yaml",
]
