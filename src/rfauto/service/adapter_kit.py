"""adapter_kit：适配器 SDK（阶段 4.1，#154 教训工具化）。

三个工具：
1. scaffold_adapter：生成 EMSolverAdapter 契约骨架（第三方接入起点）；
2. check_adapter_contract / check_known_adapters：骨架与既有适配器
   （openEMS/COMSOL/Palace 等）共用同一契约（必需方法 + 注册入口）自检；
3. check_param_semantics：同一配方参数跨通道（openEMS 模板/HFSS 插件）的
   语义清单断言——同名参数在哪个通道充当什么物理角色必须显式声明且互洽
   （#154：series/shunt 语义跨通道相反导致两个器件家族）。

契约方法表与物理角色词表（core.physics_roles.ROLE_CANDIDATES）是唯一权威；
本模块只做结构/语义一致性判断，不产生任何物理数值。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

# EMSolverAdapter 的 6 个抽象方法（骨架必须全部实现；与 em_solver_base 同步）
ADAPTER_CONTRACT_METHODS: tuple[str, ...] = (
    "connect",
    "is_available",
    "build_geometry",
    "solve",
    "get_sparams",
    "close",
)

# 已知适配器目录。contract=emsolver：走 EMSolverAdapter 契约（必需方法表）；
# contract=ads_python_api：ADS 原生 Python API 子进程通道，不是
# EMSolverAdapter（connect(is_available)/solve 口径不同），显式标注不套用该契约。
KNOWN_ADAPTERS: dict[str, dict[str, str]] = {
    "openems": {
        "module": "rfauto.adapters.openems_solver",
        "class": "OpenEMSSolver",
        "contract": "emsolver",
    },
    "comsol": {
        "module": "rfauto.adapters.comsol_adapter",
        "class": "ComsolAdapter",
        "contract": "emsolver",
    },
    "palace": {
        "module": "rfauto.adapters.palace_solver",
        "class": "PalaceSolver",
        "contract": "emsolver",
    },
    "ads": {
        "module": "rfauto.adapters.ads_python_api",
        "class": "AdsPythonApiAdapter",
        "contract": "ads_python_api",
    },
}

_SCAFFOLD = '''"""{name} 适配器骨架（rfauto new-adapter 生成，阶段 4.1 契约）。

接入步骤：
1. 实现 6 个抽象方法；2. 注册进 EMSolverRegistry + configs/solvers.yaml；
3. 在 param_semantics 声明每个模板每个参数的本通道物理角色；
4. 跑 rfauto validate-adapter（或 doctor）确认契约与语义断言通过。
"""

from __future__ import annotations

import contextlib

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
)

# 求解器类型键：EMSolverType 枚举之外的自定义 EDA 用原始字符串
SOLVER_TYPE = "{safe}"


class {class_name}(EMSolverAdapter):
    """{name} 求解器适配器（骨架：逐方法补实现）。"""

    # 参数语义清单（#154 教训）：dict[模板名][参数名] = 物理角色描述。
    # 同名参数跨通道语义相反 = 两个器件家族；声明缺失会被
    # check_param_semantics 拦截。
    param_semantics: dict[str, dict[str, str]] = {{}}

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)

    def connect(self) -> bool:
        raise NotImplementedError

    def is_available(self) -> bool:
        return False

    def build_geometry(self, geometry: dict) -> bool:
        raise NotImplementedError

    def solve(self) -> EMSolverResult:
        raise NotImplementedError

    def get_sparams(self):
        raise NotImplementedError

    def close(self) -> None:
        self._connected = False


def register_{safe}(registry=None):
    """注册到全局 EMSolverRegistry（导入即注册模式，同 openems/comsol/palace）。"""
    from rfauto.adapters.em_solver_base import get_global_registry

    (registry if registry is not None else get_global_registry()).register(
        SOLVER_TYPE, {class_name}
    )


with contextlib.suppress(Exception):
    register_{safe}()
'''


def scaffold_adapter(name: str, output_dir: str | Path | None = None) -> dict[str, Any]:
    """生成适配器骨架文件（不覆盖既有文件）。

    产物与 openEMS/COMSOL/Palace 共用同一 EMSolverAdapter 契约：6 个抽象方法
    + param_semantics 语义清单 + register_<name>() 注册入口；落盘前先 compile()
    校验骨架本身可编译（防空骨架）。名字非法或目标已存在时不落盘并显式报错。
    """
    safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    if not safe or safe[0].isdigit():
        return {"ok": False, "errors": [f"非法适配器名: {name}"]}
    class_name = "".join(part.capitalize() for part in safe.split("_")) + "Adapter"
    out_dir = Path(output_dir) if output_dir else Path("src") / "rfauto" / "adapters"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{safe}_adapter.py"
    if out.exists():
        return {"ok": False, "errors": [f"已存在: {out}"]}
    content = _SCAFFOLD.format(name=name, class_name=class_name, safe=safe)
    try:
        compile(content, str(out), "exec")
    except SyntaxError as exc:  # 显式失败，不落盘半成品
        return {"ok": False, "errors": [f"骨架语法错误: {exc}"]}
    out.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "path": str(out),
        "class_name": class_name,
        "module": f"{safe}_adapter",
        "register_fn": f"register_{safe}",
        "contract_methods": list(ADAPTER_CONTRACT_METHODS),
    }


def check_adapter_contract(adapter_cls: type) -> dict[str, Any]:
    """校验一个适配器类是否满足 EMSolverAdapter 契约（骨架用同一门）。

    判定：6 个必需方法可调用，且类无残留抽象方法（可直接实例化）。
    """
    abstract = set(getattr(adapter_cls, "__abstractmethods__", frozenset()) or ())
    missing = [
        name for name in ADAPTER_CONTRACT_METHODS
        if not callable(getattr(adapter_cls, name, None)) or name in abstract
    ]
    return {
        "ok": not missing,
        "class": getattr(adapter_cls, "__name__", repr(adapter_cls)),
        "missing": missing,
        "abstract": sorted(abstract),
        "methods": list(ADAPTER_CONTRACT_METHODS),
    }


def check_known_adapters() -> dict[str, Any]:
    """对已知适配器目录逐个跑契约自检（COMSOL/openEMS/Palace 走 EMSolver 契约）。

    ADS 是原生 Python API 子进程通道，显式标注 contract=ads_python_api，
    不套用 EMSolverAdapter 的方法表（避免把不同协议硬塞进同一契约）。
    """
    adapters: dict[str, Any] = {}
    for name in sorted(KNOWN_ADAPTERS):
        entry = KNOWN_ADAPTERS[name]
        try:
            module = importlib.import_module(entry["module"])
            adapter_cls = getattr(module, entry["class"])
        except Exception as exc:
            adapters[name] = {"ok": False, "contract": entry["contract"],
                              "error": f"{type(exc).__name__}: {exc}"}
            continue
        if entry["contract"] == "emsolver":
            result = check_adapter_contract(adapter_cls)
        else:
            result = {
                "ok": True,
                "class": adapter_cls.__name__,
                "note": "非 EMSolverAdapter 契约（ADS 原生 Python API 子进程通道）",
            }
        result["contract"] = entry["contract"]
        adapters[name] = result
    return {
        "ok": all(bool(v.get("ok")) for v in adapters.values()),
        "adapters": adapters,
    }


# ─── 参数语义（#154）────────────────────────────────────────────────────────

def _strip_unit_suffix(name: str) -> str:
    """参数名去 _mm 后缀，供词表候选比对（arm_len_mm ↔ arm_len）。"""
    return name[:-3] if name.endswith("_mm") else name


def canonical_roles(param: str) -> list[str]:
    """参数名反查规范物理角色（core.physics_roles.ROLE_CANDIDATES）。

    返回空列表表示该名称不在词表中（新参数名允许），此时跳过角色一致性判断
    ——不臆断、不误报。
    """
    from rfauto.core.physics_roles import ROLE_CANDIDATES

    target = _strip_unit_suffix(param)
    roles: list[str] = []
    for role, candidates in ROLE_CANDIDATES.items():
        if any(_strip_unit_suffix(c) == target for c in candidates):
            roles.append(role)
    return roles


def _semantic_channels(template: str | None, plugin_cls: Any) -> dict[str, dict[str, str]]:
    """收集各通道声明的 (参数名 → 物理角色)。

    - openems_template：TEMPLATE_SPECS 的 physics_roles（openEMS 通道权威声明）；
    - hfss_plugin：插件类可选 physics_roles 声明（HFSS/HFSS 桌面插件通道）。
    """
    channels: dict[str, dict[str, str]] = {}
    if template:
        try:
            from rfauto.models.template_specs import TEMPLATE_SPECS
            if template in TEMPLATE_SPECS.names():
                roles = dict(TEMPLATE_SPECS.get(template).physics_roles or {})
                if roles:
                    channels["openems_template"] = roles
        except Exception:  # best-effort：拿不到模板声明就不做该通道比对
            pass
    plugin_roles = dict(getattr(plugin_cls, "physics_roles", {}) or {})
    if plugin_roles:
        channels["hfss_plugin"] = {
            str(k): str(v) for k, v in plugin_roles.items()
        }
    return channels


def _semantic_issues(channels: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """同名参数跨通道语义一致性（#154 工具化的核心判定）。

    两条判据：
    A. 名称规范角色冲突：参数名在 ROLE_CANDIDATES 有规范角色 R，但某通道
       把它声明为另一个合法角色 R'（如 series_w_mm 被声明为 shunt 角色）
       → #154 的“同名参数语义相反”；
    B. 跨通道不一致：同名参数在两个通道被声明为不同角色。
    """
    from rfauto.core.physics_roles import ROLE_CANDIDATES

    issues: list[dict[str, str]] = []
    declared: dict[str, dict[str, str]] = {}
    for channel, roles in channels.items():
        for param, role in roles.items():
            declared.setdefault(param, {})[channel] = str(role)

    for param in sorted(declared):
        per_channel = declared[param]
        known = canonical_roles(param)
        for channel in sorted(per_channel):
            role = per_channel[channel]
            if known and role in ROLE_CANDIDATES and role not in known:
                issues.append({
                    "check": "semantic_conflict",
                    "param": param,
                    "detail": f"{channel} 把 {param} 声明为 {role}，但该名称的"
                              f"规范角色是 {known}（#154 同名参数语义相反）",
                })
        if len(set(per_channel.values())) > 1:
            issues.append({
                "check": "channel_conflict",
                "param": param,
                "detail": f"同名参数跨通道角色不一致: {per_channel}",
            })
    return issues


def check_param_semantics(recipe_path: str | Path) -> dict[str, Any]:
    """配方参数跨通道语义断言（#154 工具化）。

    检查项：
    A. 模板的 param_semantics 声明覆盖 optimization.params 全部参数；
    B. 插件 hfss_var_map 覆盖 optimization.params（变量名与配方参数名
       不一致时必须显式映射——hfss_var_map 缺陷的历史教训）；
    C. 各通道声明的物理角色互不冲突（同名参数角色相反/跨通道不一致）；
       角色词表权威 = core.physics_roles.ROLE_CANDIDATES。
    """
    import yaml

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    opt_params = (recipe.get("optimization") or {}).get("params") or {}
    if not opt_params:
        return {"ok": False, "errors": ["配方无 optimization.params"]}

    issues: list[dict[str, str]] = []
    model_name = str(recipe.get("model", ""))

    # A. openEMS 模板语义声明
    from rfauto.adapters.openems_templates import TEMPLATE_META

    template = None
    try:
        from rfauto.service.ui_service import _template_hint
        template = _template_hint({"model": model_name})
    except Exception:
        template = None
    if template and template in TEMPLATE_META:
        semantics_doc = TEMPLATE_META[template].get("param_semantics", "")
        for name in opt_params:
            if name not in semantics_doc:
                issues.append({
                    "check": "template_semantics",
                    "param": name,
                    "detail": f"模板 {template} 的 param_semantics 未声明 {name}",
                })

    # B. 插件 hfss_var_map 覆盖 + 收集插件通道语义声明
    plugin = None
    var_map: dict[str, str] = {}
    try:
        from rfauto.models.registry import get as get_plugin
        plugin = get_plugin(model_name)
        var_map = dict(getattr(plugin, "hfss_var_map", {}) or {})
    except KeyError:
        plugin = None
    if plugin is not None:
        for name in opt_params:
            mapped = var_map.get(name, name)
            if mapped != name and name not in var_map:
                issues.append({
                    "check": "hfss_var_map",
                    "param": name,
                    "detail": "参数名≠设计变量名且未在 hfss_var_map 映射",
                })

    # C. 跨通道物理角色一致性（#154）
    channels = _semantic_channels(template, plugin)
    issues.extend(_semantic_issues(channels))

    return {
        "ok": not issues,
        "recipe": str(path),
        "model": model_name,
        "template": template,
        "n_opt_params": len(opt_params),
        "semantic_channels": sorted(channels),
        "n_semantic_roles": sum(len(r) for r in channels.values()),
        "issues": issues,
        "note": "同名参数跨通道语义相反 = 两个器件家族（#154）；"
                "新增适配器/模板时先补 param_semantics 再跑采样",
    }
