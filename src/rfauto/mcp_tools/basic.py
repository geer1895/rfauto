"""doctor/list_models/validate_recipe（环境探测与配方校验）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 1. doctor ─────────────────────────────────────────────────────────────

@mcp.tool
def doctor() -> dict[str, Any]:
    """环境探测（basic 域）：AEDT/ADS 版本/license/路径/版本组合逐项体检。

    无副作用，可安全调用；只盘点环境不修复不安装，个别探测不过 →
    ok=False 且逐项 status 如实（不抛异常）。只读无时序约束。

    Returns:
        dict: {ok: bool, checks: [{name, status, detail}]}
    """
    from rfauto.service.api import doctor as _doctor
    return _doctor()


# ─── 2. list_models ────────────────────────────────────────────────────────

@mcp.tool
def list_models() -> dict[str, Any]:
    """列出已注册的模型插件。

    无副作用，可安全调用。

    Returns:
        dict: {ok: bool, models: [str], load_errors: [str]}
        （load_errors=插件加载失败账本，AU-7 可见化；缺省空列表）
    """
    from rfauto.service.api import list_models as _list_models
    return _list_models()


# ─── 3. validate_recipe ────────────────────────────────────────────────────

@mcp.tool
def validate_recipe(recipe_path: str) -> dict[str, Any]:
    """校验配方文件（recipe 域）：YAML 路径 → 结构校验结论，不执行仿真。

    无副作用，可安全调用；不用于参数提案或运行控制。路径不存在/格式
    非法 → errors 列表逐条如实。只读无时序约束。

    Args:
        recipe_path: 配方文件路径（YAML 格式）

    Returns:
        dict: {ok: bool, errors: [str], warnings: [str]}；文件缺失/解析
        失败 → ok=False 且 errors 说明原因
    """
    from rfauto.service.api import validate_recipe as _validate_recipe
    return _validate_recipe(recipe_path)
