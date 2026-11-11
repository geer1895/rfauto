"""format_overview MCP 工具组——格式速览 agent 面（T-Q5 批 3 接线席 Q-W9-3，
aurora_q 方向 C）。

零逻辑转发 service/format_overview_service.overview_format（规则 4；CLI
同源面=rfauto vendor-docs 域外另有 format_overview 纯 MCP 工具——T-Q5 批 3
"MCP 工具化（可读无 MCP 四面补齐）"列项，速览层只读无副作用故不上 CLI 叶，
Agent 直读面）。速览层 8 kind：touchstone/kicad_pcb/drawio/gdsii/dxf/
ipc2581/odbpp/ads_ds（schema 版本与解析边界见 service 模块 docstring）。

- ``format_overview``：格式文件 → 结构化速览信封（stats 统计+entities 关键
  实体+summary 结构摘要）；未知格式/坏文件显式报错信封（非异常裸抛）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

__all__ = ["format_overview"]


@mcp.tool
def format_overview(path: str, kind: str | None = None) -> dict[str, Any]:
    """格式速览（"一屏看懂"）：EDA/设计格式文件 → Agent 可读结构化 JSON。

    只读零副作用（不写盘不执行）。8 kind：touchstone（.sNp）/kicad_pcb/
    drawio/gdsii/.dxf/ipc2581（.xml）/odbpp（目录或 .tgz）/ads_ds（ADS
    .ds EEsof dataset——magic 形态+字节序标记+格式版本+STRINGDATA 变量名；
    数值数据块专有布局未解，速览只承诺头部+变量名面）。探测=目录形态/
    扩展名/magic 头三通道；未知格式/坏文件显式报错信封不裸抛。

    Args:
        path: 格式文件或目录路径（.sNp/.kicad_pcb/.drawio/.gds/.dxf/.xml/
            .tgz/ODB++ 目录/.ds）。
        kind: 显式 kind（须在已注册 kind 词表内）；None=自动探测。

    Returns:
        dict: ok=True 时 {ok, kind, schema_version, framework_version,
        path, stats, entities, summary}；ok=False 时 {ok, errors, kind,
        path}。
    """
    from rfauto.service.format_overview_service import overview_format

    return overview_format(path, kind=kind)
