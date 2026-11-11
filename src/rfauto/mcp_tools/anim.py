"""anim MCP 工具组——动图渲染 agent 面（T-Q3 接线席 Q-W5-2R，aurora_q 方向 B）。

零逻辑转发 service/anim_render_service（规则 4；CLI ``rfauto anim render``
同源同名 service 函数，JSON 信封出）。渲染/自检全在 service/animation
内核（铁律 7：零物理数值生产——本模块只做 spec 路径与输出路径搬运）。

- ``anim_render``：spec JSON 文件 → SVG 动画（确定性逐字节可复现，sha256
  钉）；``out="-"`` 不落盘（SVG 原文进信封 ``svg_str``，文本信道消费）；
  缺省写 spec 同目录同名 ``.svg``。spec 违约/数据源缺失按
  ``category=io|spec|data`` 分类信封（不炸会话）。

spec schema 权威出口：docs/tutorials/rf-animation.md（教程章）+
rfauto.service.animation.spec 模块 docstring（chart_type 必填、
source/sources 二选一、16 图型/11 数据源 kind 词表）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

__all__ = ["anim_render"]


@mcp.tool
def anim_render(spec_path: str, out: str | None = None,
                self_check: bool = False) -> dict[str, Any]:
    """动图渲染（anim 域）：声明式 spec JSON → SVG 动画文件（确定性逐字节复现，sha256 钉）。

    spec 声明 chart_type（16 内建图型）+ source(s)（11 数据源 kind：
    sparams_csv/snip/trials/anchor_json/field_dump/layout_json/
    cascade_json/nf2ff_cut/chain_json/symbols_json/budget_json）+
    canvas/style/animation；全部数字只从确定性数据源读出，缺数据显式
    报错（category=data）不画空图。同 spec 两跑逐字节同。失败按
    ``category=io|spec|data`` 分类（io=文件缺失/不可读/落盘失败，
    spec=spec 违约/未知图型，data=数据源缺失/残缺）。

    Args:
        spec_path: spec JSON 文件路径（schema 见 docs/tutorials/rf-animation.md
            或 rfauto.service.animation.spec 模块 docstring）。
        out: SVG 输出路径；None=spec 同目录同名 .svg；"-"=不落盘
            （SVG 原文进信封 svg_str 字段，供 Agent 直接消费文本）。
        self_check: True=渲染后附加自动化体检（结构/帧序/文字挤压声明式
            估算，warn 级不拦路；信封附 self_check 字段；SVG 输出不受
            开关影响逐字节同）。

    Returns:
        dict: ok=True 时 {svg_path, svg_bytes, sha256, chart_type,
        frame_count, duration_s, data_sources, warnings, [self_check],
        [svg_str], file_sha256_matches}；ok=False 时 {errors, category}。
    """
    from rfauto.service.anim_render_service import anim_render

    return anim_render(spec_path, out=out, self_check=self_check)
