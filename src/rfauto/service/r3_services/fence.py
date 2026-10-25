"""r3_services.fence —— 文件浏览栅栏（fs_read_fence/fs_list）与配方目录列举（list_recipes）。

自 r3_services.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原「文件浏览与配方目录」节逐字节搬迁。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

# ─── 文件浏览（工程导入选文件）与配方目录 ────────────────────────────────────

#: 敏感面单源（S-1/S-3，code_audit_slice6）：configs/ 目录承载凭据
#: （chat_settings.yaml 含 LLM API key、remote_machines.local.yaml 含远程
#: 主机凭据），*.local.yaml 是本机覆盖配置、同样不入暴露面。
FS_SENSITIVE_DIR_NAMES = frozenset({"configs"})
FS_SENSITIVE_FILE_NAMES = frozenset({"chat_settings.yaml"})


def fs_allowed_roots() -> list[Path]:
    """文件暴露面（fs_list / recipe_view）的允许根（单源）。

    允许根 = 当前工作目录 + 环境变量 ``RFAUTO_FS_ROOT``（``os.pathsep``
    分隔可设多个，如 Windows 下 ``D:\\proj;E:\\data``）。UI 的文件浏览与
    配方读都以这组根做围栏，越界一律显式报错（见 :func:`fs_read_fence`）。
    """
    roots = [Path.cwd().resolve()]
    for part in os.environ.get("RFAUTO_FS_ROOT", "").split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).resolve())
    return roots


def _fs_within_roots(target: Path, roots: list[Path]) -> bool:
    """target（应已 resolve）是否落在任一允许根内。

    #318 铁律：Windows 路径比较必须 os.path.normcase（大小写/分隔符不敏感）；
    根边界用"normcase 后 == 根 或 以 根+os.sep 为前缀"判定，防前缀串扰
    （如 C:\\ab 不算 C:\\a 的子路径）。
    """
    t = os.path.normcase(str(Path(target).resolve()))
    for r in roots:
        rt = os.path.normcase(str(r))
        if t == rt or t.startswith(rt.rstrip("\\/") + os.sep):
            return True
    return False


def _fs_sensitive_dir_hit(resolved: Path) -> bool:
    """路径任一分量（含自身）名为 configs 即命中凭据目录。"""
    return any(p.name.lower() in FS_SENSITIVE_DIR_NAMES
               for p in (resolved, *resolved.parents))


def fs_read_fence(
    path: str | Path, allow_outside_roots: bool = False
) -> str | None:
    """读路径围栏（S-1 列举 / S-3 单文件读共用）：拒绝返回错误消息，放行 None。

    三条规则（依次判定）：
    1. 敏感目录：路径任一分量名为 ``configs``（含 target 就是 configs 目录）
       ——凭据面不暴露，任何根内/根外、任何放行参数都拒；
    2. 敏感文件：文件名 ``*.local.yaml`` 或 ``chat_settings.yaml``——同上，
       ``allow_outside_roots`` 只放宽根围栏、不放宽敏感过滤；
    3. 根围栏（``allow_outside_roots=False`` 时）：resolve + normcase 后必须
       落在 :func:`fs_allowed_roots` 之一内。错误消息指明允许根与
       RFAUTO_FS_ROOT 出口，信封由调用方原样透传前端。
    """
    target = Path(path)
    resolved = target.resolve()
    if _fs_sensitive_dir_hit(resolved):
        return f"敏感目录（configs，凭据面）不可访问: {target}"
    low = resolved.name.lower()
    if low.endswith(".local.yaml") or low in FS_SENSITIVE_FILE_NAMES:
        return (f"敏感文件不可访问: {target}"
                "（*.local.yaml / chat_settings.yaml 为凭据面）")
    if not allow_outside_roots:
        roots = fs_allowed_roots()
        if not _fs_within_roots(resolved, roots):
            allowed = "; ".join(str(r) for r in roots)
            return (f"路径越界: {target}（允许根: {allowed}；"
                    "如需其他根可设 RFAUTO_FS_ROOT 环境变量）")
    return None


def fs_list(path: str = "") -> dict[str, Any]:
    """列出目录内容（目录 + 工程相关文件），供导入向导选文件。

    根围栏（S-1，code_audit_slice6 审查）：/api/fs/list 是 loopback HTTP
    暴露面，path 不设防时任意目录（系统盘/凭据目录）可被远程枚举。允许根
    见 :func:`fs_allowed_roots`（cwd + RFAUTO_FS_ROOT），经
    :func:`fs_read_fence` 判定（normcase 比较，#318），越界/敏感目录返回
    ``{"ok": False, "error": ...}``（ui/server 路由信封原样透传）。
    敏感条目过滤：名为 configs 的子目录、``*.local.yaml`` 与
    ``chat_settings.yaml`` 文件不进 entries；返回形状
    ok/path/parent/entries 与围栏前完全一致。
    """
    target = Path(path) if path else Path.cwd()
    fence_err = fs_read_fence(target)
    if fence_err is not None:
        return {"ok": False, "error": fence_err}
    if not target.exists() or not target.is_dir():
        return {"ok": False, "error": f"目录不存在: {target}"}
    entries = []
    try:
        for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if e.name.startswith("."):
                continue
            low = e.name.lower()
            if e.is_dir() and low in FS_SENSITIVE_DIR_NAMES:
                continue  # 凭据目录（configs/）不进暴露面
            if e.is_file() and (low.endswith(".local.yaml")
                                or low in FS_SENSITIVE_FILE_NAMES):
                continue  # 凭据文件（*.local.yaml / chat_settings.yaml）不进暴露面
            kind = "dir" if e.is_dir() else "file"
            # Touchstone（WP0.3/E8 S 参数页外部导入）与工程文件同列
            if e.is_file() and e.suffix.lower() not in (
                ".aedt", ".yaml", ".yml", ".wbpz",
                ".s1p", ".s2p", ".s3p", ".s4p",
            ):
                continue
            entries.append({"name": e.name, "path": str(e), "kind": kind})
    except PermissionError:
        return {"ok": False, "error": f"无权限读取: {target}"}
    return ok_envelope(path=str(target), parent=str(target.parent), entries=entries)


RECIPE_HELP = {
    "model": "仿真模型（插件名），如 wilkinson_power_divider / patch_antenna；决定参数集与 fake 解析模型",
    "params": "可调参数及当前值；HFSS 通道经 hfss_var_map 映射到工程变量名",
    "setup": "扫频范围（freq_range_ghz）与点数，决定 S 参数曲线覆盖的频段",
    "objectives": "目标（如 s11_db 带内 max_below -15）：定义'好'的标准，是优化与诊断的裁判",
    "optimization": "优化器配置：每个参数的 low/high 范围、trial 数、采样器（TPE/CMA-ES）",
    "fidelity": "多保真开关：fake 粗筛 → HFSS/openEMS 精算（P0 gate 校验排序一致性）",
}

#: 工作副本"人工审阅入库"提示（C22，TODO:417 followUp）。指向既有 promote/
#: 审批面（rfauto inbox 审批收件箱，propose→approve→apply 三层 Gate），
#: 不新增后端命令——工作副本按守卫设计不自动回写 recipes/ 原件。
WORKCOPY_REVIEW_HINT = (
    "本条是 runs/recipe_workcopy/ 工作副本，recipes/ 原件未被改动。"
    "人工审阅：先与原件 diff 对比确认改动；入库：经既有审批链"
    "（rfauto inbox 审批收件箱，propose→approve→apply 三层 Gate）"
    "或人工确认后显式写回原件并 git commit 留痕。"
)


def _workcopy_root() -> Path:
    """工作副本根（与 infra.recipe_guard.WORKCOPY_SUBDIR 同源单源）。"""
    from rfauto.infra.recipe_guard import WORKCOPY_SUBDIR

    return Path(*WORKCOPY_SUBDIR)


def _scan_recipe_dir(root: Path, kind: str) -> list[dict[str, Any]]:
    """扫描一个配方目录 -> 条目列表（kind: original|workcopy，#105 单文件不阻塞）。"""
    import yaml

    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.yaml")):
        entry: dict[str, Any]
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            entry = {
                "path": str(p).replace("\\", "/"),
                "kind": kind,
                "model": data.get("model", "?"),
                "n_params": len(data.get("params", {})),
                "n_objectives": len(data.get("objectives", [])),
                "freq_range": (data.get("setup", {}) or {}).get("freq_range_ghz", []),
            }
        except Exception as exc:  # 单文件解析失败不阻塞目录（#105）
            entry = {"path": str(p).replace("\\", "/"), "kind": kind,
                     "model": f"<解析失败: {exc}>"}
        if kind == "workcopy":
            entry["source_recipe"] = "recipes/" + p.relative_to(root).as_posix()
            entry["review_hint"] = WORKCOPY_REVIEW_HINT
        out.append(entry)
    return out


def list_recipes() -> dict[str, Any]:
    """扫描 recipes/ 原件与 runs/recipe_workcopy/ 工作副本，分组返回（C22）。

    分组字段（JSON 进出，前端只渲染）：``recipes`` 键保持只含 recipes/
    原件（既有消费者零改动——LLM 配方菜单与模糊解析都消费它），工作副本
    单列 ``workcopies``（每条附 ``source_recipe`` 反查原件路径与
    ``review_hint`` 人工审阅入库提示），``groups`` 给分组计数；两列表的
    每条都带 ``kind``（original/workcopy）。
    """
    originals = _scan_recipe_dir(Path("recipes"), "original")
    workcopies = _scan_recipe_dir(_workcopy_root(), "workcopy")
    return ok_envelope(
        recipes=originals,
        workcopies=workcopies,
        groups={"originals": len(originals), "workcopies": len(workcopies)},
        help=RECIPE_HELP,
    )
