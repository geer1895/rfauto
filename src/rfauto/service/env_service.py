"""环境变量体检服务（QW-12 doctor --env 的 service 面，JSON 进出）。

消费者：CLI `doctor --env`。MCP 不暴露（参考/体检面非工具面）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.infra.env_vars import build_env_report


def doctor_env() -> dict[str, Any]:
    """全仓 RFAUTO_* 环境变量体检报告。

    返回：{checks: [逐条目行], summary: {total, set, missing, default}}。
    missing（path 类设了但不存在）是唯一问题态；缺省回落不是问题
    （工具未安装属正常态）。退出码判断留给 CLI 薄壳。
    """
    checks = build_env_report()
    missing = sum(1 for c in checks if c["state"] == "missing")
    return {
        "checks": checks,
        "summary": {
            "total": len(checks),
            "set": sum(1 for c in checks if c["set"]),
            "missing": missing,
            "default": sum(1 for c in checks if c["state"] == "default"),
        },
    }


# ---------------------------------------------------------------------------
# extras 安装状态面板（UX-A1，2026-10-04 rx-batch2）
# ---------------------------------------------------------------------------

# 场景 → extras 组速查（新用户"第 31 分钟"的第一坑：30 组选择逻辑只在
# pyproject 注释里——R4 外壳审计 A1-1/A5 提案，落此为机读面）。
EXTRA_SCENES: dict[str, tuple[str, ...]] = {
    "真机仿真": ("hfss", "openems", "comsol", "ngsolve", "remote"),
    "测量仪器": ("vna", "vna-sim"),
    "优化与代理": ("smt", "gbdt", "gnn", "torch", "jax", "multiobj"),
    "UI 与报告": ("ui", "viz3d", "report"),
    "MCP/agent": ("mcp",),
    "数据集/湖": ("dataset", "zstandard"),
    "版图与制造": ("layout", "fab"),
    "文档站": ("docs",),
    "开发": ("dev",),
}


def _requirement_name(req: str) -> str:
    """从 requirement 串提发行名（packaging 解析失败回退轻量切分）。"""
    try:
        from packaging.requirements import Requirement

        return Requirement(req).name
    except Exception:
        for sep in (";", ">=", "<", "==", "~=", "!=", "[", " ", "#"):
            req = req.split(sep)[0]
        return req.strip()


def doctor_extras(pyproject_path: Path | None = None) -> dict[str, Any]:
    """逐 extras 组的安装状态体检（UX-A1；信息性报告，不做退出码判断）。

    数据源=pyproject [project.optional-dependencies] 机读；探测=
    importlib.metadata 按发行名查版本（缺=未装，如实呈现非问题态——
    extras 未装是正常态，#122 不凑绿）。输出：
    {groups:[{name,n_reqs,n_installed,missing:[…]}], scenes:[…], summary:{…}}。
    """
    from importlib import metadata as _md

    import tomllib

    path = Path(pyproject_path) if pyproject_path else Path(__file__).resolve().parents[3] / "pyproject.toml"
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
        extras: dict[str, list[str]] = table.get("project", {}).get(
            "optional-dependencies", {}
        )
    except (OSError, tomllib.TOMLDecodeError):
        extras = {}

    version_cache: dict[str, str | None] = {}

    def _probe(name: str) -> str | None:
        if name not in version_cache:
            try:
                version_cache[name] = _md.version(name)
            except _md.PackageNotFoundError:
                version_cache[name] = None
            except Exception:  # 观测性 best-effort（#105）：元数据异常不阻塞
                version_cache[name] = None
        return version_cache[name]

    groups: list[dict[str, Any]] = []
    for gname in sorted(extras):
        reqs = extras[gname]
        missing: list[str] = []
        for req in reqs:
            if not str(req).strip() or str(req).strip().startswith("-r"):
                continue
            name = _requirement_name(str(req))
            if _probe(name) is None:
                missing.append(name)
        groups.append(
            {
                "name": gname,
                "n_reqs": len(reqs),
                "n_installed": len(reqs) - len(missing),
                "missing": missing,
            }
        )

    by_name = {g["name"]: g for g in groups}
    scenes: list[dict[str, Any]] = []
    for scene, members in EXTRA_SCENES.items():
        hits = [by_name[m] for m in members if m in by_name]
        if not hits:
            continue
        ready = all(not h["missing"] for h in hits)
        scenes.append(
            {
                "scene": scene,
                "groups": [h["name"] for h in hits],
                "ready": ready,
                "partial": [h["name"] for h in hits if h["missing"]],
            }
        )

    return {
        "groups": groups,
        "scenes": scenes,
        "summary": {
            "n_groups": len(groups),
            "fully_installed": sum(1 for g in groups if not g["missing"]),
        },
    }
