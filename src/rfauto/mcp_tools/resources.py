"""@mcp.resource 只读资源七件（runs 索引/materials/compat/terminology/toolsets/calculators 目录/datasets 目录）——不计入工具数（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动；2026-10-01 月终门 C1 勘误：terminology 资源的 __file__ 锚深随拆分修正 parents[2]→[3]，回到仓根、与 terminology_service 同源；2026-10-05 W5-D EC-6 +1 toolsets 工具集目录资源；2026-10-14 架构批 MCP-B 席 +2 calculators/datasets 目录资源——Agent 发现面，与同名工具同源 service 单点）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── MCP resources（E4c 版本化只读资源，v2 尾巴） ────────────────────────────
# 资源只读、无副作用；内容与 CLI/服务层同源（注册表 runs 表 + YAML 知识库文件）。

@mcp.resource("rfauto://runs/index")
def runs_index_resource() -> dict[str, Any]:
    """runs 索引（缺省注册表最近 20 条，同 run_store.list_runs）。"""
    from rfauto.infra.run_store import list_runs
    return {"runs": list_runs(limit=20)}


@mcp.resource("rfauto://knowledge/materials")
def materials_resource() -> dict[str, Any]:
    """材料库（configs/materials.yaml 原文结构）。"""
    # AU-5 单点：cwd 相对 open → core/materials 单点发现（仓根 cwd 下
    # 解析到同一文件；子目录 cwd 不再 FileNotFoundError）。
    from rfauto.core.materials import load_materials_yaml

    return load_materials_yaml()


@mcp.resource("rfauto://knowledge/compat_matrix")
def compat_matrix_resource() -> dict[str, Any]:
    """版本兼容矩阵（knowledge/compat_matrix.yaml 原文结构）。"""
    import yaml

    with open("knowledge/compat_matrix.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@mcp.resource("rfauto://knowledge/terminology")
def terminology_resource() -> dict[str, Any]:
    """术语卡（knowledge/terminology.yaml 原文结构；QW-6，服务层同源
    terminology_service——同一 __file__ 锚定，CWD 无关）。"""
    import yaml

    # parents[3]=仓根（本文件 src/rfauto/mcp_tools/ 三层深；AU-1 自
    # mcp_server.py 拆分时原 parents[2] 锚随目录变深漂到 src/——2026-10-01
    # 月终门 C1 修正，锚语义与 service/terminology_service.py 同源）
    _root = Path(__file__).resolve().parents[3]
    with (_root / "knowledge" / "terminology.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@mcp.resource("rfauto://toolsets/definition")
def toolsets_definition_resource() -> dict[str, Any]:
    """工具集目录（EC-6，W5-D）：每条目 name/description/skill/tools——
    pyaedt-mcp toolsets://definition 同形态（本仓保持 rfauto:// scheme，
    spec §2.2.2 一致性裁决）；tools 成员按注册面自动枚举（单一真源），
    tools_hint 与注册面漂移 → ok=False errors 显式（不凑）。
    service/toolsets_service.build_toolsets_definition 同源薄资源。"""
    from rfauto.service.toolsets_service import build_toolsets_definition

    return build_toolsets_definition()


@mcp.resource("rfauto://calculators/index")
def calculators_index_resource() -> dict[str, Any]:
    """计算器注册表目录（只读）：名单/说明/参数表（mm/GHz/Ω/dB 口径）。

    service/calculator_service.list_calculators 同源薄资源（全量含实验
    键，experimental 标签在册——与 list_calculators 工具同参同源）；
    执行走 run_calculator 工具。纯清单面恒 ok=True，空注册如实回空清单。
    """
    from rfauto.service.calculator_service import list_calculators

    return list_calculators(include_experimental=True)


@mcp.resource("rfauto://datasets/index")
def datasets_index_resource() -> dict[str, Any]:
    """数据集注册表总览（只读）：逐数据集点数/GT/可见性 manifest 汇总。

    service/dataset_insights.list_datasets 同源薄资源（盘面 manifest 自动
    汇总非手工名单——与 list_datasets 工具同参同源）；行级查询走
    query_dataset 工具。目录缺失=ok 空清单如实（不臆造）。
    """
    from rfauto.service.dataset_insights import list_datasets

    return list_datasets()
