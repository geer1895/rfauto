"""r3_services.solvers —— 求解器注册面（6g 可视化协议 + 6h 管理 + spice 工具状态）。

自 r3_services.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体自原「6g/6h」节逐字节搬迁；governance（变更应用）与 chat（工具映射）从这里单向导入，包内零环。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# ─── 6g: Solver Visualization Protocol ────────────────────────────────────────

def list_solver_visualizations(solver_name: str | None = None) -> dict[str, Any]:
    """List available visualizations from registered solvers.

    6g: Each adapter declares visualizations() -> [{kind, spec}].
    UI renders by kind; unknown kinds degrade to file download.
    """
    from rfauto.adapters import (  # noqa: F401 - 注册副作用
        comsol_adapter,
        elmer_adapter,
        openems_solver,
        palace_solver,
    )
    from rfauto.adapters.em_solver_base import get_global_registry
    registry = get_global_registry()

    results = []
    for stype, solver_cls in registry._solvers.items():
        # W8-S36（审查波 2 P2-2）：原式 `solver_name and stype.value if
        # hasattr(...) else str(stype) != solver_name` 按条件表达式优先级
        # 解析为 `(solver_name and stype.value) if hasattr(...) else (...)`
        # ——带名过滤恒 continue（空表）、str 键无过滤恒排除。归一为
        # label 后"名称给出 AND 不匹配"两条件同层（照抄 ：94 双形态防御）。
        label = stype.value if hasattr(stype, "value") else str(stype)
        if solver_name and label != solver_name:
            continue
        # Instantiate with minimal config to query visualizations
        try:
            from rfauto.adapters.em_solver_base import EMSolverConfig
            config = EMSolverConfig(solver_type=stype)
            instance = solver_cls(config)
            viz = instance.visualizations()
            results.append({
                "solver": stype.value if hasattr(stype, "value") else str(stype),
                "visualizations": viz,
                "output_formats": instance.supported_output_formats(),
            })
        except Exception as e:
            results.append({
                "solver": stype.value if hasattr(stype, "value") else str(stype),
                "error": str(e),
                "visualizations": [],
            })

    return ok_envelope(solvers=results)


# ─── 6h: Solver Management ────────────────────────────────────────────────────

def list_registered_solvers() -> dict[str, Any]:
    """List all registered solvers with their status.

    6h: UI reads EMSolverRegistry + shows availability.
    """
    from rfauto.adapters import (  # noqa: F401 - 注册副作用
        comsol_adapter,
        elmer_adapter,
        openems_solver,
        palace_solver,
    )
    from rfauto.adapters.em_solver_base import EMSolverConfig, get_global_registry
    registry = get_global_registry()

    solvers = []
    for stype, solver_cls in registry._solvers.items():
        try:
            config = EMSolverConfig(solver_type=stype)
            instance = solver_cls(config)
            available = instance.is_available()
            viz = instance.visualizations()
        except Exception:
            available = False
            viz = []
        # gpl 子包（pypo/scuff）注册键为 str 字面（ge8c 席5 gpl 隔离设计），
        # 枚举键取 .value、str 键取自身——双形态防御（#105；终门八百一十九
        # 实证：全模块 import 冒烟后 str 键致 AttributeError 污染下游）。
        type_label = stype.value if hasattr(stype, "value") else str(stype)
        solvers.append({
            "type": type_label,
            "class": solver_cls.__name__,
            "available": available,
            "n_visualizations": len(viz),
        })

    return ok_envelope(solvers=solvers, total=len(solvers))


def add_solver_to_config(
    name: str,
    solver_type: str,
    exe_path: str | None = None,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a solver entry to configs/solvers.yaml.

    6h: UI wizard writes solver config; human can add CST/COMSOL etc.

    写入 schema 与 em_solver_base.load_solvers_config 的读取约定一致：
    `solvers:` 包裹 + 每条目 `solver_type` 字段（审查缺口 #7 修复——
    曾写顶层 {name: {type}}，运行时永远读不到）。
    """
    import yaml

    config_path = Path("configs") / "solvers.yaml"
    if not config_path.parent.exists():
        config_path.parent.mkdir(parents=True)

    data: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    # 注意：不能用 setdefault("solvers", {}) or {}——空 dict 为 falsy 时 or 会
    # 返回脱离 data 的新字典，后续写入全部丢失（本次修复的实测陷阱）
    solvers = data.get("solvers")
    if not isinstance(solvers, dict):
        solvers = {}
        data["solvers"] = solvers

    if name in solvers:
        return error_envelope([f"Solver '{name}' already exists"])

    entry: dict[str, Any] = {"solver_type": solver_type}
    if exe_path:
        entry["exe_path"] = exe_path
    if extra_params:
        entry.update(extra_params)
    solvers[name] = entry

    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # 回读校验：确保写入的条目能被 load_solvers_config 读到（链路级验证）
    from rfauto.adapters.em_solver_base import load_solvers_config
    loaded = load_solvers_config(config_path)
    readable = name in loaded
    return ok_envelope(
        name=name,
        config_path=str(config_path),
        entry=entry,
        loadable=readable,
        errors=[] if readable else ["entry written but not loadable by load_solvers_config"],
    )


def remove_solver_from_config(name: str) -> dict[str, Any]:
    """Remove a solver entry from configs/solvers.yaml."""
    import yaml

    config_path = Path("configs") / "solvers.yaml"
    if not config_path.exists():
        return error_envelope(["configs/solvers.yaml not found"])

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    solvers = data.get("solvers") or {}

    if name not in solvers:
        return error_envelope([f"Solver '{name}' not found in config"])

    removed = solvers.pop(name)
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ok_envelope(name=name, removed=removed)


def spice_tool_status(path: str | Path | None = None) -> dict[str, Any]:
    """ngspice/Xyce 电路级参考通道探测（6h 管理页数据源，0ca followUp④）。

    读 configs/solvers.yaml 的 ``ngspice``/``xyce`` 节（管理页探测记录，
    非 EM 求解器——无 EMSolverAdapter，不进 EMSolverRegistry）并逐项调用
    adapters.spice_netlist 的探测钩子（resolve_*/available）。两项独立
    best-effort（观测性 #105）：单工具探测失败只入该工具的 error 字段，
    不阻塞另一项，也不影响 EM 求解器管理面。
    """
    from rfauto.adapters import spice_netlist as sn
    from rfauto.adapters.em_solver_base import load_solvers_config

    configs = load_solvers_config(path)
    tools: dict[str, Any] = {}
    probes = {
        "ngspice": (sn.resolve_ngspice_exe, sn.ngspice_available,
                    "RFAUTO_NGSPICE_BIN > tools/ngspice/Spice64/bin > PATH"),
        "xyce": (sn.resolve_xyce_exe, sn.xyce_available,
                 "RFAUTO_XYCE_BIN > PATH"),
    }
    for name, (resolve_fn, available_fn, chain) in probes.items():
        entry = configs.get(name)
        tool: dict[str, Any] = {
            "configured": entry is not None,
            "available": False,
            "exe": None,
            "resolve_chain": chain,
            "error": None,
        }
        try:
            tool["available"] = bool(available_fn())
            if tool["available"]:
                tool["exe"] = str(resolve_fn())
        except Exception as exc:  # 探测只报告不抛（#105）
            tool["error"] = str(exc)
        tools[name] = tool
    return ok_envelope(
        tools=tools,
        note="电路级 SPICE 通道（探测记录）；EM 求解器管理面见 "
                "list_registered_solvers（EMSolverRegistry）",
    )
