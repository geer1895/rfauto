"""动图渲染服务面（T-Q3 接线席 Q-W5-2，aurora_q 方向 B，2026-11-04）。

spec JSON 文件进出 + SVG 落盘的薄壳（规则 4：CLI ``rfauto anim render``
与 MCP ``anim_render`` 工具同源同名 service 函数，JSON 信封出）。

零数值逻辑转发 service/animation 内核（铁律 7：本模块不产生任何物理数字
——渲染全在 animation.renderers 注册表内核完成，本模块只做文件 IO+异常
分类+信封搬运）。内核面（render_animation/parse_animation_spec/
AnimationDataError/AnimationSpecError）**冻结只消费**（接线席禁改清单；
本模块是 animation/ 包外的兄弟 service 文件，不触内核目录）。

信封（service/envelope 构造器单源，#105：分类文案带指引不抛裸异常）：

- ``ok=True``：{svg_path, svg_bytes, sha256, chart_type, frame_count,
  duration_s, data_sources, warnings}``；``self_check=True`` 时附
  ``self_check`` 字段（报告 to_dict 形态：ok/n_errors/n_warnings/issues）；
  ``out="-"`` 时不落盘、附 ``svg_str`` 字段（SVG 原文走信封，文本信道
  消费）；
- ``ok=False``：{errors, category}``——category ∈ {"io"|"spec"|"data"}：
  - ``io``=spec 文件缺失/不可读/非 JSON 对象/SVG 落盘失败；
  - ``spec``=AnimationSpecError（spec 违约/未知图型/源数量不合）——
    文案附 schema 指引（教程章+内核 spec 模块 docstring）；
  - ``data``=AnimationDataError（数据源缺失/残缺）——内核指引文案原样
    透传，附数据源排查指引。

输出落点（大 SVG 走文件更稳——缺省写文件+信封给路径与 sha256）：

- ``out=None``：spec 同目录同名 ``.svg``（``spec.json``→``spec.svg``）；
- ``out="<path>"``：显式落点（父目录自动创建）；
- ``out="-"``：不落盘，SVG 原文进信封 ``svg_str``（Agent/管道抓文本用）。

确定性：内核同 spec 两跑逐字节同（sha256 钉）；落盘走 ``write_bytes``
（零平台换行翻译），信封 sha256 == 落盘文件字节 sha256。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rfauto.service.animation import (
    AnimationDataError,
    AnimationError,
    AnimationSpecError,
    available_chart_types,
    render_animation,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["anim_render"]

#: spec 违约指引（错误信封第二行；schema 权威出口两处）
_SPEC_HINT = (
    "spec schema 见 docs/tutorials/rf-animation.md 或 "
    "rfauto.service.animation.spec 模块 docstring（chart_type 必填；"
    "source/sources 二选一；未知键/缺必填/图型未注册均显式报错）")

#: 数据源排查指引（内核 AnimationDataError 指引文案之外的第二行）
_DATA_HINT = (
    "排查：核对 spec.source(s).kind 在 11 kind 词表内+path 指向真实产物"
    "（run 湖/仿真产物/锚点 JSON）+columns 与产物表头一致；kind 契约见 "
    "docs/tutorials/rf-animation.md 数据源节")


def _default_out_path(spec_path: Path) -> Path:
    """缺省 SVG 落点：spec 同目录同名 ``.svg``。"""
    return spec_path.with_suffix(".svg")


def anim_render(spec_path: str, *, out: str | None = None,
                self_check: bool = False) -> dict[str, Any]:
    """spec JSON 文件 → SVG 动画文件（确定性渲染；JSON 信封出）。

    Args:
        spec_path: spec JSON 文件路径（声明式 spec：chart_type+source(s)
            +canvas/style/animation；schema 见内核 spec 模块 docstring）。
        out: SVG 输出路径；None=spec 同目录同名 ``.svg``；``"-"``=不落盘
            （SVG 原文进信封 ``svg_str``）。
        self_check: True=渲染后附加自动化体检（结构/帧序/文字挤压声明式
            估算；warn 级=提示不拦路），信封附 ``self_check`` 字段——
            SVG 输出不受开关影响（逐字节同，内核零变化钉）。

    Returns:
        dict: ok 信封（见模块 docstring）；失败分类 category=io|spec|data。
    """
    # ── spec 文件读面（io 分类）────────────────────────────────────────────
    p = Path(spec_path)
    if not p.is_file():
        return error_envelope(
            [f"spec 文件不存在: {p}",
             "先落盘 spec JSON（形态见 docs/tutorials/rf-animation.md）"],
            category="io")
    try:
        raw = p.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return error_envelope([f"spec 文件不可读: {exc}"], category="io")
    try:
        spec: Any = json.loads(raw)
    except ValueError as exc:
        return error_envelope(
            [f"spec 不是合法 JSON: {exc}", _SPEC_HINT], category="io")
    if not isinstance(spec, dict):
        return error_envelope(
            [f"spec 必须是 JSON 对象，收到 {type(spec).__name__}",
             _SPEC_HINT], category="io")

    # ── 渲染（内核冻结面；异常分类 spec/data）──────────────────────────────
    try:
        result = render_animation(spec, self_check=self_check)
    except AnimationSpecError as exc:
        return error_envelope([f"spec 违约: {exc}", _SPEC_HINT],
                              category="spec")
    except AnimationDataError as exc:
        return error_envelope([f"数据源缺失/残缺: {exc}", _DATA_HINT],
                              category="data")
    except AnimationError as exc:  # 防御性（家族基类，新子类兜底）
        return error_envelope([f"动图渲染失败: {exc}"], category="spec")

    fields: dict[str, Any] = {
        "sha256": result.sha256,
        "chart_type": result.chart_type,
        "frame_count": result.frame_count,
        "duration_s": result.duration_s,
        "data_sources": list(result.data_sources),
        "warnings": list(result.warnings),
    }
    if self_check:
        # AnimationSelfCheckedResult（isinstance AnimationResult 恒成立）
        fields["self_check"] = result.self_check.to_dict()  # type: ignore[attr-defined]

    # ── SVG 落点（文件 / stdout 文本两态互斥）─────────────────────────────
    if out == "-":
        fields["svg_path"] = "-"
        fields["svg_str"] = result.svg_str
        return ok_envelope(**fields)

    target = _default_out_path(p) if out is None else Path(out)
    try:
        parent = target.parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        payload = result.svg_str.encode("utf-8")
        target.write_bytes(payload)
    except OSError as exc:
        return error_envelope(
            [f"SVG 落盘失败: {exc}",
             "核对 --out 路径可写（或省略 --out 落 spec 同目录缺省名）"],
            category="io")
    fields["svg_path"] = str(target)
    fields["svg_bytes"] = len(payload)
    # 落盘字节即 svg_str 的 utf-8 原文（write_bytes 零换行翻译）——
    # 信封 sha256 == 文件字节 sha256（验收钉：test_anim_cli 落盘复核）。
    fields["file_sha256_matches"] = (
        hashlib.sha256(payload).hexdigest() == result.sha256)
    return ok_envelope(**fields)


def anim_chart_types() -> dict[str, Any]:
    """已注册图型清单（只读观测面；16 内建图型自注册序）。"""
    return ok_envelope(chart_types=list(available_chart_types()),
                       n_chart_types=len(available_chart_types()))
